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

from PIL import Image, ImageOps

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
_GOOGLE_VISION_MIN_WIDTH = 1200


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
    is_cumulative_total: bool,
) -> float | None:
    text = "".join(word for word, _ in numeric_words)
    number = _number_from_token(text)
    if (
        number is None
        or not is_cumulative_total
        or any("." in word or "," in word for word, _ in numeric_words)
    ):
        return number

    digit_groups = [
        group
        for word, _ in numeric_words
        for group in re.findall(r"[0-9OQIL]+", word.upper())
    ]
    if len(digit_groups) < 2:
        return number

    # Vision can replace the PIUSI total's decimal mark with a space.
    inferred_number = _number_from_token(
        f"{digit_groups[0]}.{''.join(digit_groups[1:])}"
    )
    return inferred_number if inferred_number is not None else number


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


def _google_vision_word_lines(
    document: dict[str, object],
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
            is_cumulative_total=len(readings) == 1,
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
        image_content = _prepare_google_vision_image(content)
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
                    "image": {"content": base64.b64encode(image_content).decode("ascii")},
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
    return _parse_google_vision_response(response_data)


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
        with Image.open(BytesIO(content)) as source:
            image = ImageOps.autocontrast(source.convert("L"))
            if image.width < 1200:
                scale = 1200 / image.width
                image = image.resize(
                    (1200, round(image.height * scale)),
                    Image.Resampling.LANCZOS,
                )
        results = [
            parse_meter_ocr_data(
                pytesseract.image_to_data(
                    image,
                    config=f"--psm {page_segmentation}",
                    output_type=Output.DICT,
                )
            )
            for page_segmentation in (6, 11)
        ]
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
    default_provider = (
        "google_vision"
        if os.environ.get("FUEL_ENV", "").strip().lower() == "production"
        else "tesseract"
    )
    provider = os.environ.get("FUEL_OCR_PROVIDER", default_provider).strip().lower()
    if provider == "google_vision":
        api_key = os.environ.get("GOOGLE_CLOUD_VISION_API_KEY", "").strip()
        if not api_key:
            return MeterOcrResult(
                status="unavailable",
                message=(
                    "Google Vision is selected, but "
                    "GOOGLE_CLOUD_VISION_API_KEY is not configured."
                ),
            )
        return _extract_google_vision_readings(content, api_key)
    if provider != "tesseract":
        return MeterOcrResult(
            status="failed",
            message=f"Unsupported OCR provider: {provider}.",
        )
    return _extract_tesseract_readings(content)
