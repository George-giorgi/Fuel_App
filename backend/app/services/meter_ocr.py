import base64
from dataclasses import dataclass
from io import BytesIO
import json
import os
import re
import shutil
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from PIL import Image, ImageFilter, ImageOps

from backend.app.core.config import METER_OCR_MIN_CONFIDENCE


_TESSERACT_PATHS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    "/opt/local/bin/tesseract",
    "/usr/local/bin/tesseract",
    "/opt/homebrew/bin/tesseract",
)
_GOOGLE_VISION_ENDPOINT = "https://vision.googleapis.com/v1/images:annotate"
_GOOGLE_VISION_TIMEOUT_SECONDS = 20
_GOOGLE_VISION_CROP = (0.08, 0.35, 0.92, 0.78)
_GOOGLE_VISION_CURRENT_ROW_CROP = (0.18, 0.41, 0.80, 0.56)
_GOOGLE_VISION_TOTAL_ROW_CROP = (0.18, 0.54, 0.80, 0.70)
_GOOGLE_VISION_MIN_WIDTH = 1200
_GOOGLE_VISION_CURRENT_ROW_MIN_WIDTH = 1600
_GOOGLE_VISION_TOTAL_ROW_MIN_WIDTH = 1600


@dataclass(frozen=True)
class MeterOcrResult:
    status: str
    current_fill_litres: float | None = None
    cumulative_total_litres: float | None = None
    current_fill_confidence: float | None = None
    cumulative_total_confidence: float | None = None
    message: str | None = None


def _number_from_token(value: str) -> float | None:
    if not any(character.isdigit() for character in value):
        return None
    normalized = value.upper().replace("O", "0").replace("Q", "0")
    normalized = normalized.replace("I", "1").replace("L", "1")
    match = re.search(r"[0-9]+(?:[.,][0-9]+)*", normalized)
    if match is None:
        return None

    number = match.group()
    if "." in number and "," in number:
        number = number.replace(",", "")
    elif "," in number:
        number = number.replace(",", ".")
    if number.count(".") > 1:
        whole, _, fraction = number.rpartition(".")
        number = whole.replace(".", "") + "." + fraction
    try:
        return float(number)
    except ValueError:
        return None


def _number_from_google_vision_words(
    numeric_words: list[tuple[str, float]],
    *,
    infer_decimal_from_word_groups: bool,
    decimal_places: int | None = None,
) -> float | None:
    text = "".join(word for word, _ in numeric_words)
    number = _number_from_token(text)
    if number is None or not infer_decimal_from_word_groups:
        return number

    digit_groups = [
        group
        for word, _ in numeric_words
        for group in re.findall(r"[0-9OQIL]+", word.upper())
    ]
    if decimal_places is not None:
        digits = "".join(digit_groups)
        if len(digits) <= decimal_places:
            return None
        return _number_from_token(
            f"{digits[:-decimal_places]}.{digits[-decimal_places:]}"
        )

    if any("." in word or "," in word for word, _ in numeric_words):
        return number
    if len(digit_groups) >= 2:
        # Vision can replace a PIUSI row's decimal mark with a space.
        inferred_number = _number_from_token(
            f"{digit_groups[0]}.{''.join(digit_groups[1:])}"
        )
        return inferred_number if inferred_number is not None else number

    return number


def parse_meter_ocr_data(
    data: dict[str, list[object]],
    min_confidence: float = METER_OCR_MIN_CONFIDENCE,
) -> MeterOcrResult:
    lines: dict[tuple[int, int, int], dict[str, object]] = {}
    texts = data.get("text", [])
    for index, raw_text in enumerate(texts):
        value = str(raw_text).strip()
        if not value:
            continue
        try:
            confidence = float(data["conf"][index])
            top = int(data["top"][index])
            key = (
                int(data["block_num"][index]),
                int(data["par_num"][index]),
                int(data["line_num"][index]),
            )
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        line = lines.setdefault(key, {"top": top, "words": []})
        line["top"] = min(int(line["top"]), top)
        line["words"].append((value, confidence))

    readings = []
    for line in lines.values():
        candidates = [
            (number, confidence)
            for word, confidence in line["words"]
            if (number := _number_from_token(word)) is not None
        ]
        if not candidates:
            continue
        number, confidence = max(
            candidates, key=lambda candidate: len(str(candidate[0]))
        )
        readings.append((int(line["top"]), number, confidence))

    readings.sort(key=lambda reading: reading[0])
    if len(readings) < 2:
        return MeterOcrResult(
            status="uncertain",
            message=(
                "Could not confidently read two numeric lines. The first line is "
                "the current fill and the second is the cumulative total."
            ),
        )

    _, current_fill, current_confidence = readings[0]
    _, cumulative_total, cumulative_confidence = readings[1]
    if current_fill <= 0:
        return MeterOcrResult(
            status="uncertain",
            current_fill_litres=current_fill,
            cumulative_total_litres=cumulative_total,
            current_fill_confidence=current_confidence,
            cumulative_total_confidence=cumulative_confidence,
            message="The first-line fill was read as zero; check the PIUSI display.",
        )
    confidences = (current_confidence, cumulative_confidence)
    if min(confidences) < min_confidence:
        message = (
            "One or both readings are low-confidence. Retake a close, well-lit "
            "photo of large digits written with a dark marker."
        )
        status = "uncertain"
    else:
        message = None
        status = "ready"
    return MeterOcrResult(
        status=status,
        current_fill_litres=current_fill,
        cumulative_total_litres=cumulative_total,
        current_fill_confidence=current_confidence,
        cumulative_total_confidence=cumulative_confidence,
        message=message,
    )


def _get_tesseract_command() -> str:
    configured_command = os.environ.get("TESSERACT_CMD", "").strip()
    if configured_command:
        return configured_command
    on_path = shutil.which("tesseract")
    if on_path is not None:
        return on_path
    for candidate in _TESSERACT_PATHS:
        if os.access(candidate, os.X_OK):
            return candidate
    return "tesseract"


def _prepare_google_vision_image(content: bytes) -> bytes:
    with Image.open(BytesIO(content)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")

    width, height = image.size
    left, top, right, bottom = (
        round(width * _GOOGLE_VISION_CROP[0]),
        round(height * _GOOGLE_VISION_CROP[1]),
        round(width * _GOOGLE_VISION_CROP[2]),
        round(height * _GOOGLE_VISION_CROP[3]),
    )
    if right <= left or bottom <= top:
        raise ValueError("The photo is too small to crop the meter display.")

    image = image.crop((left, top, right, bottom))
    if image.width < _GOOGLE_VISION_MIN_WIDTH:
        scale = _GOOGLE_VISION_MIN_WIDTH / image.width
        image = image.resize(
            (_GOOGLE_VISION_MIN_WIDTH, round(image.height * scale)),
            Image.Resampling.LANCZOS,
        )

    prepared = BytesIO()
    image.save(prepared, format="JPEG", quality=95)
    return prepared.getvalue()


def _prepare_google_vision_row_image(
    content: bytes,
    crop_bounds: tuple[float, float, float, float],
    min_width: int,
) -> bytes:
    with Image.open(BytesIO(content)) as source:
        image = ImageOps.exif_transpose(source).convert("L")

    width, height = image.size
    left, top, right, bottom = (
        round(width * crop_bounds[0]),
        round(height * crop_bounds[1]),
        round(width * crop_bounds[2]),
        round(height * crop_bounds[3]),
    )
    if right <= left or bottom <= top:
        raise ValueError("The photo is too small to crop the meter display row.")

    image = ImageOps.autocontrast(image.crop((left, top, right, bottom)), cutoff=1)
    image = image.filter(ImageFilter.UnsharpMask(radius=2, percent=150, threshold=3))
    if image.width < min_width:
        scale = min_width / image.width
        image = image.resize(
            (min_width, round(image.height * scale)),
            Image.Resampling.LANCZOS,
        )

    prepared = BytesIO()
    image.save(prepared, format="JPEG", quality=95)
    return prepared.getvalue()


def _google_vision_word_lines(
    document: dict[str, object],
    *,
    infer_decimal_from_word_groups: bool = False,
    decimal_places_by_row: tuple[int, ...] | None = None,
) -> list[tuple[int, str, float]]:
    words = []
    pages = document.get("pages", [])
    if not isinstance(pages, list):
        return []
    for page in pages:
        if not isinstance(page, dict):
            continue
        blocks = page.get("blocks", [])
        if not isinstance(blocks, list):
            continue
        for block in blocks:
            if not isinstance(block, dict):
                continue
            paragraphs = block.get("paragraphs", [])
            if not isinstance(paragraphs, list):
                continue
            for paragraph in paragraphs:
                if not isinstance(paragraph, dict):
                    continue
                paragraph_words = paragraph.get("words", [])
                if not isinstance(paragraph_words, list):
                    continue
                for word in paragraph_words:
                    if not isinstance(word, dict):
                        continue
                    symbols = word.get("symbols", [])
                    if not isinstance(symbols, list):
                        continue
                    text = "".join(
                        str(symbol.get("text", ""))
                        for symbol in symbols
                        if isinstance(symbol, dict)
                    )
                    if not text:
                        continue
                    bounding_box = word.get("boundingBox", {})
                    if not isinstance(bounding_box, dict):
                        bounding_box = {}
                    vertices = bounding_box.get("vertices", [])
                    if not isinstance(vertices, list):
                        vertices = []
                    y_values = [
                        float(vertex.get("y", 0))
                        for vertex in vertices
                        if isinstance(vertex, dict)
                    ]
                    x_values = [
                        float(vertex.get("x", 0))
                        for vertex in vertices
                        if isinstance(vertex, dict)
                    ]
                    top = min(y_values, default=0.0)
                    bottom = max(y_values, default=top)
                    left = min(x_values, default=0.0)
                    center = (top + bottom) / 2
                    height = max(bottom - top, 1.0)
                    try:
                        confidence = float(word.get("confidence", 0.0)) * 100
                    except (TypeError, ValueError):
                        confidence = 0.0
                    words.append((center, left, height, text, confidence))

    lines: list[dict[str, object]] = []
    for center, left, height, text, confidence in sorted(
        words, key=lambda word: (word[0], word[1])
    ):
        line = next(
            (
                item
                for item in lines
                if abs(center - float(item["center"]))
                <= max(8.0, min(height, float(item["height"])) * 0.55)
            ),
            None,
        )
        if line is None:
            line = {
                "center": center,
                "height": height,
                "words": [],
            }
            lines.append(line)
        line_words = line["words"]
        line_words.append((center, left, text, confidence))
        line["center"] = sum(
            (word[0] for word in line_words), 0.0
        ) / len(line_words)

    readings = []
    for line in sorted(lines, key=lambda item: float(item["center"])):
        numeric_words = [
            (text, confidence)
            for _, _, text, confidence in sorted(
                line["words"], key=lambda word: word[1]
            )
            if any(character.isdigit() for character in text)
            or text.strip() in {".", ","}
        ]
        if not numeric_words:
            continue
        number = _number_from_google_vision_words(
            numeric_words,
            infer_decimal_from_word_groups=(
                infer_decimal_from_word_groups or len(readings) == 1
            ),
            decimal_places=(
                decimal_places_by_row[len(readings)]
                if decimal_places_by_row is not None
                and len(readings) < len(decimal_places_by_row)
                else None
            ),
        )
        if number is None:
            continue
        confidence = sum(
            confidence
            for text, confidence in numeric_words
            if any(character.isdigit() for character in text)
        ) / sum(
            1
            for text, _ in numeric_words
            if any(character.isdigit() for character in text)
        )
        readings.append((int(float(line["center"])), str(number), confidence))
    return readings


def _parse_google_vision_response(response_data: object) -> MeterOcrResult:
    if not isinstance(response_data, dict):
        return MeterOcrResult(
            status="failed",
            message="Google Vision returned an invalid response.",
        )
    responses = response_data.get("responses")
    if not isinstance(responses, list) or not responses or not isinstance(responses[0], dict):
        return MeterOcrResult(
            status="failed",
            message="Google Vision returned no OCR response.",
        )
    vision_response = responses[0]
    api_error = vision_response.get("error")
    if isinstance(api_error, dict):
        message = api_error.get("message", "The OCR request was rejected.")
        return MeterOcrResult(
            status="failed",
            message=f"Google Vision error: {message}",
        )
    document = vision_response.get("fullTextAnnotation")
    if not isinstance(document, dict):
        return MeterOcrResult(
            status="uncertain",
            message="Google Vision could not find readable text in this photo.",
        )
    readings = _google_vision_word_lines(document)
    if len(readings) < 2:
        return MeterOcrResult(
            status="uncertain",
            message=(
                "Could not confidently read two numeric lines. The first line is "
                "the current fill and the second is the cumulative total."
            ),
        )

    data: dict[str, list[object]] = {
        "text": [reading[1] for reading in readings],
        "conf": [reading[2] for reading in readings],
        "top": [reading[0] for reading in readings],
        "block_num": [1 for _ in readings],
        "par_num": [1 for _ in readings],
        "line_num": list(range(1, len(readings) + 1)),
    }
    return parse_meter_ocr_data(data)


def _extract_google_vision_readings(
    content: bytes,
    api_key: str,
) -> MeterOcrResult:
    try:
        display_content = _prepare_google_vision_image(content)
        current_row_content = _prepare_google_vision_row_image(
            content,
            _GOOGLE_VISION_CURRENT_ROW_CROP,
            _GOOGLE_VISION_CURRENT_ROW_MIN_WIDTH,
        )
        total_row_content = _prepare_google_vision_row_image(
            content,
            _GOOGLE_VISION_TOTAL_ROW_CROP,
            _GOOGLE_VISION_TOTAL_ROW_MIN_WIDTH,
        )
    except (OSError, ValueError, Image.DecompressionBombError):
        return MeterOcrResult(
            status="failed",
            message="Could not prepare this photo for Google Vision. Retake it and try again.",
        )

    url = f"{_GOOGLE_VISION_ENDPOINT}?{urlencode({'key': api_key})}"
    request_body = json.dumps(
        {
            "requests": [
                {
                    "image": {
                        "content": base64.b64encode(display_content).decode("ascii")
                    },
                    "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
                },
                {
                    "image": {
                        "content": base64.b64encode(current_row_content).decode(
                            "ascii"
                        )
                    },
                    "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
                },
                {
                    "image": {
                        "content": base64.b64encode(total_row_content).decode("ascii")
                    },
                    "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
                }
            ]
        }
    ).encode("utf-8")
    request = Request(
        url,
        data=request_body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=_GOOGLE_VISION_TIMEOUT_SECONDS) as response:
            response_data = json.loads(response.read())
    except HTTPError as error:
        return MeterOcrResult(
            status="failed",
            message=(
                f"Google Vision request failed (HTTP {error.code}). Check the "
                "API key, billing, and request quota."
            ),
        )
    except URLError as error:
        return MeterOcrResult(
            status="failed",
            message=f"Could not connect to Google Vision: {error.reason}",
        )
    except TimeoutError:
        return MeterOcrResult(
            status="failed",
            message="Google Vision OCR timed out. Please try again.",
        )
    except (json.JSONDecodeError, UnicodeDecodeError):
        return MeterOcrResult(
            status="failed",
            message="Google Vision returned an invalid response.",
        )

    if not isinstance(response_data, dict):
        return MeterOcrResult(
            status="failed",
            message="Google Vision returned an invalid response.",
        )
    responses = response_data.get("responses")
    if (
        not isinstance(responses, list)
        or len(responses) < 3
        or not isinstance(responses[0], dict)
        or not isinstance(responses[1], dict)
        or not isinstance(responses[2], dict)
    ):
        return MeterOcrResult(
            status="failed",
            message="Google Vision did not return results for all meter display crops.",
        )

    display_result = _parse_google_vision_response(
        {"responses": [responses[0]]}
    )
    if display_result.status == "failed":
        return display_result
    if (
        display_result.current_fill_litres is None
        or display_result.current_fill_confidence is None
    ):
        return display_result

    display_document = responses[0].get("fullTextAnnotation")
    display_readings = (
        _google_vision_word_lines(
            display_document,
            infer_decimal_from_word_groups=True,
            decimal_places_by_row=(3, 4),
        )
        if isinstance(display_document, dict)
        else []
    )
    display_current = display_readings[0] if display_readings else None

    current_response = responses[1]
    current_error = current_response.get("error")
    if isinstance(current_error, dict) and display_current is None:
        message = current_error.get("message", "The OCR request was rejected.")
        return MeterOcrResult(
            status="failed",
            message=f"Google Vision error reading the current-fill row: {message}",
        )
    current_document = current_response.get("fullTextAnnotation")
    current_readings = (
        _google_vision_word_lines(
            current_document,
            infer_decimal_from_word_groups=True,
            decimal_places_by_row=(3,),
        )
        if isinstance(current_document, dict)
        else []
    )
    current_reading = (
        current_readings[0]
        if current_readings
        else display_current
    )
    if current_reading is None:
        return MeterOcrResult(
            status="uncertain",
            current_fill_litres=display_result.current_fill_litres,
            current_fill_confidence=display_result.current_fill_confidence,
            message="Google Vision could not read the current-fill row. Retake the photo.",
        )

    total_response = responses[2]
    api_error = total_response.get("error")
    if isinstance(api_error, dict):
        message = api_error.get("message", "The OCR request was rejected.")
        return MeterOcrResult(
            status="failed",
            message=f"Google Vision error reading the cumulative row: {message}",
        )
    total_document = total_response.get("fullTextAnnotation")
    if not isinstance(total_document, dict):
        return MeterOcrResult(
            status="uncertain",
            current_fill_litres=display_result.current_fill_litres,
            current_fill_confidence=display_result.current_fill_confidence,
            message="Google Vision could not read the PIUSI TOTAL row. Retake the photo.",
        )

    total_readings = _google_vision_word_lines(
        total_document,
        infer_decimal_from_word_groups=True,
        decimal_places_by_row=(4,),
    )
    if not total_readings:
        return MeterOcrResult(
            status="uncertain",
            current_fill_litres=display_result.current_fill_litres,
            current_fill_confidence=display_result.current_fill_confidence,
            message="Google Vision could not read the PIUSI TOTAL row. Retake the photo.",
        )

    _, current_text, current_confidence = current_reading
    _, total_text, total_confidence = total_readings[0]
    return parse_meter_ocr_data(
        {
            "text": [
                current_text,
                total_text,
            ],
            "conf": [
                current_confidence,
                total_confidence,
            ],
            "top": [0, 1],
            "block_num": [1, 1],
            "par_num": [1, 1],
            "line_num": [1, 2],
        }
    )


def _resize_for_tesseract(image: Image.Image) -> Image.Image:
    width, height = image.size
    scale = min(1600 / width if width < 1600 else 1, 2400 / max(width, height))
    if scale != 1:
        image = image.resize(
            (round(width * scale), round(height * scale)),
            Image.Resampling.LANCZOS,
        )
    return image


def _prepare_tesseract_images(content: bytes) -> list[Image.Image]:
    with Image.open(BytesIO(content)) as source:
        image = ImageOps.exif_transpose(source).convert("L")

    image = ImageOps.autocontrast(image)
    width, height = image.size
    left, top, right, bottom = (
        round(width * _GOOGLE_VISION_CROP[0]),
        round(height * _GOOGLE_VISION_CROP[1]),
        round(width * _GOOGLE_VISION_CROP[2]),
        round(height * _GOOGLE_VISION_CROP[3]),
    )
    crop = _resize_for_tesseract(image.crop((left, top, right, bottom)))
    thresholded = crop.point(lambda pixel: 255 if pixel > 150 else 0)
    return [
        _resize_for_tesseract(image),
        crop,
        thresholded,
        ImageOps.invert(thresholded),
    ]


def _extract_tesseract_readings(content: bytes) -> MeterOcrResult:
    try:
        import pytesseract
        from pytesseract import Output
        from pytesseract.pytesseract import TesseractError, TesseractNotFoundError
    except ModuleNotFoundError:
        return MeterOcrResult(
            status="unavailable",
            message="Install the local pytesseract package to enable meter OCR.",
        )

    pytesseract.pytesseract.tesseract_cmd = _get_tesseract_command()
    try:
        images = _prepare_tesseract_images(content)
        results = []
        for image_index, image in enumerate(images):
            page_segmentations = (6, 11) if image_index < 2 else (6,)
            for page_segmentation in page_segmentations:
                for whitelist in (False, True):
                    config = f"--psm {page_segmentation}"
                    if whitelist:
                        config += " -c tessedit_char_whitelist=0123456789.,"
                    result = parse_meter_ocr_data(
                        pytesseract.image_to_data(
                            image,
                            config=config,
                            output_type=Output.DICT,
                        )
                    )
                    results.append(result)
                    if (
                        result.status == "ready"
                        and result.current_fill_confidence is not None
                        and result.cumulative_total_confidence is not None
                        and min(
                            result.current_fill_confidence,
                            result.cumulative_total_confidence,
                        ) >= METER_OCR_MIN_CONFIDENCE + 15
                    ):
                        return result
    except TesseractNotFoundError:
        return MeterOcrResult(
            status="unavailable",
            message=(
                "The local Tesseract executable is not installed or is not on PATH."
            ),
        )
    except TesseractError as error:
        return MeterOcrResult(
            status="failed",
            message=f"Local Tesseract OCR failed: {error}",
        )

    return max(
        results,
        key=lambda result: (
            result.current_fill_litres is not None
            and result.cumulative_total_litres is not None,
            min(
                result.current_fill_confidence or 0,
                result.cumulative_total_confidence or 0,
            ),
        ),
    )


def extract_meter_readings(content: bytes) -> MeterOcrResult:
    vision_api_key = os.environ.get("GOOGLE_CLOUD_VISION_API_KEY", "").strip()
    default_provider = (
        "google_vision"
        if (
            os.environ.get("FUEL_ENV", "").strip().lower() == "production"
            or vision_api_key
        )
        else "tesseract"
    )
    provider = os.environ.get("FUEL_OCR_PROVIDER", default_provider).strip().lower()
    if provider == "google_vision":
        if not vision_api_key:
            return MeterOcrResult(
                status="unavailable",
                message=(
                    "Google Vision is selected, but "
                    "GOOGLE_CLOUD_VISION_API_KEY is not configured."
                ),
            )
        return _extract_google_vision_readings(content, vision_api_key)
    if provider != "tesseract":
        return MeterOcrResult(
            status="failed",
            message=f"Unsupported OCR provider: {provider}.",
        )
    return _extract_tesseract_readings(content)
