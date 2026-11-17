import base64
from dataclasses import dataclass, replace
from decimal import Decimal
from io import BytesIO
import json
import os
import re
import shutil
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import cv2
from PIL import Image, ImageFilter, ImageOps

from backend.app.core.config import METER_OCR_MIN_CONFIDENCE
from backend.app.services.piusi_lcd import (
    PiusiLcdRecognition,
    PiusiTotalRecognition,
    recognize_piusi_lcd,
    recognize_piusi_total,
)


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
_GOOGLE_VISION_MIN_CONFIDENCE = 80.0


@dataclass(frozen=True)
class MeterOcrResult:
    status: str
    current_fill_litres: int | None = None
    cumulative_total_litres: float | None = None
    current_fill_confidence: float | None = None
    cumulative_total_confidence: float | None = None
    message: str | None = None
    provider: str | None = None
    current_fill_raw_digits: str | None = None
    current_fill_decimal_position: int | None = None
    cumulative_total_raw_digits: str | None = None
    cumulative_total_decimal_position: int | None = None
    current_fill_segment_confidence: float | None = None
    cumulative_total_segment_confidence: float | None = None
    warnings: tuple[str, ...] = ()


def _number_from_token(value: str) -> Decimal | None:
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
        parsed = Decimal(number)
        return parsed if parsed.is_finite() else None
    except (ValueError, ArithmeticError):
        return None


def _raw_digits_and_decimal_position(value: str) -> tuple[str | None, int | None]:
    normalized = value.upper().replace("O", "0").replace("Q", "0")
    normalized = normalized.replace("I", "1").replace("L", "1")
    digits = "".join(re.findall(r"[0-9]", normalized))
    if not digits:
        return None, None
    separators = [index for index, character in enumerate(normalized) if character in ".,:"]
    if len(separators) != 1:
        return digits, None
    separator = separators[0]
    before = len(re.findall(r"[0-9]", normalized[:separator]))
    after = len(re.findall(r"[0-9]", normalized[separator + 1 :]))
    if before == 0 or after == 0:
        return digits, None
    return digits, before


def _whole_number_from_digits(digits: str | None) -> int | None:
    if not digits or not digits.isascii() or not digits.isdigit():
        return None
    return int(digits)


def _cumulative_total_litres_from_digits(digits: str | None) -> float | None:
    value = _whole_number_from_digits(digits)
    return value / 1000 if value is not None else None


def _ascii_digits(value: str) -> str | None:
    digits = "".join(character for character in value if character in "0123456789")
    return digits or None


def _number_from_google_vision_words(
    numeric_words: list[tuple[str, float]],
) -> Decimal | None:
    return _number_from_token("".join(word for word, _ in numeric_words))


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
            (number, confidence, word)
            for word, confidence in line["words"]
            if (number := _number_from_token(word)) is not None
        ]
        if not candidates:
            continue
        number, confidence, raw_text = max(
            candidates, key=lambda candidate: len(str(candidate[0]))
        )
        raw_digits, decimal_position = _raw_digits_and_decimal_position(raw_text)
        readings.append(
            (
                int(line["top"]),
                number,
                confidence,
                raw_text,
                raw_digits,
                decimal_position,
            )
        )

    readings.sort(key=lambda reading: reading[0])
    if len(readings) < 2:
        return MeterOcrResult(
            status="uncertain",
            message=(
                "Could not confidently read two numeric lines. The first line is "
                "the current fill and the second is the cumulative total."
            ),
        )

    (
        _,
        _,
        current_confidence,
        _,
        current_raw_digits,
        _,
    ) = readings[0]
    (
        _,
        _,
        cumulative_confidence,
        total_text,
        _,
        _,
    ) = readings[1]
    current_fill = _whole_number_from_digits(current_raw_digits)
    total_raw_digits = _ascii_digits(total_text)
    cumulative_total = _cumulative_total_litres_from_digits(total_raw_digits)
    if current_fill is None or current_fill <= 0:
        return MeterOcrResult(
            status="uncertain",
            current_fill_litres=current_fill,
            cumulative_total_litres=cumulative_total,
            current_fill_confidence=current_confidence,
            cumulative_total_confidence=cumulative_confidence,
            message=(
                "Could not read all current-fill digits. Review the photo."
                if current_fill is None
                else "The first-line fill was read as zero; check the PIUSI display."
            ),
            current_fill_raw_digits=current_raw_digits,
            current_fill_decimal_position=(
                max(0, len(current_raw_digits) - 3)
                if current_raw_digits is not None
                else None
            ),
            cumulative_total_raw_digits=total_raw_digits,
            cumulative_total_decimal_position=(
                max(0, len(total_raw_digits) - 3)
                if total_raw_digits is not None
                else None
            ),
        )
    if cumulative_total is None:
        return MeterOcrResult(
            status="uncertain",
            current_fill_litres=current_fill,
            current_fill_confidence=current_confidence,
            cumulative_total_confidence=cumulative_confidence,
            message="Could not read all cumulative-total digits. Review the photo.",
            current_fill_raw_digits=current_raw_digits,
            current_fill_decimal_position=(
                max(0, len(current_raw_digits) - 3)
                if current_raw_digits is not None
                else None
            ),
            cumulative_total_raw_digits=total_raw_digits,
            cumulative_total_decimal_position=(
                max(0, len(total_raw_digits) - 3)
                if total_raw_digits is not None
                else None
            ),
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
        current_fill_raw_digits=current_raw_digits,
        current_fill_decimal_position=(
            max(0, len(current_raw_digits) - 3)
            if current_raw_digits is not None
            else None
        ),
        cumulative_total_raw_digits=total_raw_digits,
        cumulative_total_decimal_position=(
            max(0, len(total_raw_digits) - 3)
            if total_raw_digits is not None
            else None
        ),
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


def _prepare_google_vision_detected_image(
    content: bytes,
    *,
    grayscale: bool,
    min_width: int,
) -> bytes:
    with Image.open(BytesIO(content)) as source:
        image = ImageOps.exif_transpose(source)
        image = image.convert("L" if grayscale else "RGB")
    if grayscale:
        image = ImageOps.autocontrast(image, cutoff=1)
        image = image.filter(
            ImageFilter.UnsharpMask(radius=2, percent=160, threshold=3)
        )
    if image.width < min_width:
        scale = min_width / image.width
        image = image.resize(
            (min_width, round(image.height * scale)),
            Image.Resampling.LANCZOS,
        )
    prepared = BytesIO()
    image.save(prepared, format="JPEG", quality=96)
    return prepared.getvalue()


def _google_vision_bottom_numeric_row_bounds(
    document: dict[str, object],
) -> tuple[int, int, int, int] | None:
    words = []
    pages = document.get("pages", [])
    if not isinstance(pages, list):
        return None
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
                    if not any(character.isdigit() for character in text):
                        continue
                    bounding_box = word.get("boundingBox", {})
                    if not isinstance(bounding_box, dict):
                        continue
                    vertices = bounding_box.get("vertices", [])
                    if not isinstance(vertices, list):
                        continue
                    coordinates = [
                        (float(vertex.get("x", 0)), float(vertex.get("y", 0)))
                        for vertex in vertices
                        if isinstance(vertex, dict)
                    ]
                    if not coordinates:
                        continue
                    left = min(point[0] for point in coordinates)
                    top = min(point[1] for point in coordinates)
                    right = max(point[0] for point in coordinates)
                    bottom = max(point[1] for point in coordinates)
                    center = (top + bottom) / 2
                    height = max(bottom - top, 1.0)
                    words.append((center, left, top, right, bottom, height))

    lines: list[dict[str, object]] = []
    for word in sorted(words, key=lambda item: (item[0], item[1])):
        center, left, top, right, bottom, height = word
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
        line_words.append(word)
        line["center"] = sum(item[0] for item in line_words) / len(line_words)

    if len(lines) < 2:
        return None
    bottom_line = max(lines, key=lambda line: float(line["center"]))
    numeric_words = bottom_line["words"]
    left = min(word[1] for word in numeric_words)
    top = min(word[2] for word in numeric_words)
    right = max(word[3] for word in numeric_words)
    bottom = max(word[4] for word in numeric_words)
    return round(left), round(top), round(right), round(bottom)


def _prepare_google_vision_detected_row_image(
    display_content: bytes,
    document: dict[str, object],
) -> bytes | None:
    bounds = _google_vision_bottom_numeric_row_bounds(document)
    if bounds is None:
        return None

    with Image.open(BytesIO(display_content)) as source:
        image = ImageOps.exif_transpose(source).convert("L")
    left, top, right, bottom = bounds
    row_height = max(bottom - top, 1)
    horizontal_padding = max(16, round(row_height * 0.75))
    vertical_padding = max(12, round(row_height * 0.45))
    crop_bounds = (
        max(0, left - horizontal_padding),
        max(0, top - vertical_padding),
        min(image.width, right + horizontal_padding),
        min(image.height, bottom + vertical_padding),
    )
    if crop_bounds[2] <= crop_bounds[0] or crop_bounds[3] <= crop_bounds[1]:
        return None

    image = ImageOps.autocontrast(image.crop(crop_bounds), cutoff=1)
    image = image.filter(ImageFilter.UnsharpMask(radius=2, percent=180, threshold=2))
    if image.width < _GOOGLE_VISION_TOTAL_ROW_MIN_WIDTH:
        scale = _GOOGLE_VISION_TOTAL_ROW_MIN_WIDTH / image.width
        image = image.resize(
            (_GOOGLE_VISION_TOTAL_ROW_MIN_WIDTH, round(image.height * scale)),
            Image.Resampling.LANCZOS,
        )
    prepared = BytesIO()
    image.save(prepared, format="JPEG", quality=98)
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
        raw_text = "".join(word for word, _ in numeric_words)
        if _number_from_google_vision_words(numeric_words) is None:
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
        readings.append((int(float(line["center"])), raw_text, confidence))
    return readings


def _google_vision_text_annotation_lines(
    response: dict[str, object],
) -> list[tuple[int, str, float]]:
    annotations = response.get("textAnnotations")
    if not isinstance(annotations, list):
        return []
    words = []
    for annotation in annotations[1:]:
        if not isinstance(annotation, dict):
            continue
        text = str(annotation.get("description", ""))
        if not any(character.isdigit() for character in text):
            continue
        polygon = annotation.get("boundingPoly", {})
        vertices = polygon.get("vertices", []) if isinstance(polygon, dict) else []
        if not isinstance(vertices, list):
            continue
        points = [
            (float(vertex.get("x", 0)), float(vertex.get("y", 0)))
            for vertex in vertices
            if isinstance(vertex, dict)
        ]
        if not points:
            continue
        left = min(point[0] for point in points)
        top = min(point[1] for point in points)
        bottom = max(point[1] for point in points)
        words.append(((top + bottom) / 2, left, max(bottom - top, 1), text))

    lines: list[dict[str, object]] = []
    for center, left, height, text in sorted(
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
            line = {"center": center, "height": height, "words": []}
            lines.append(line)
        line_words = line["words"]
        line_words.append((center, left, text))
        line["center"] = sum(word[0] for word in line_words) / len(line_words)

    readings = []
    for line in sorted(lines, key=lambda item: float(item["center"])):
        text = "".join(
            word[2]
            for word in sorted(line["words"], key=lambda word: word[1])
            if any(character.isdigit() for character in word[2])
            or word[2].strip() in {".", ","}
        )
        if _number_from_token(text) is not None:
            readings.append((int(float(line["center"])), text, 0.0))
    return readings


def _google_vision_response_lines(
    response: dict[str, object],
) -> list[tuple[int, str, float]]:
    document = response.get("fullTextAnnotation")
    if isinstance(document, dict):
        return _google_vision_word_lines(document)
    return _google_vision_text_annotation_lines(response)


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
        readings = _google_vision_text_annotation_lines(vision_response)
        if len(readings) < 2:
            return MeterOcrResult(
                status="uncertain",
                message="Google Vision could not find two readable numeric rows.",
            )
        data: dict[str, list[object]] = {
            "text": [reading[1] for reading in readings],
            "conf": [reading[2] for reading in readings],
            "top": [reading[0] for reading in readings],
            "block_num": [1 for _ in readings],
            "par_num": [1 for _ in readings],
            "line_num": list(range(1, len(readings) + 1)),
        }
        return replace(
            parse_meter_ocr_data(data),
            status="uncertain",
            message=(
                "Only TEXT_DETECTION evidence was available; confidence is "
                "insufficient for automatic verification."
            ),
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


def _google_vision_text_detection_disagrees(
    response: dict[str, object],
    document: dict[str, object],
) -> bool:
    annotations = response.get("textAnnotations")
    document_text = document.get("text")
    if (
        not isinstance(annotations, list)
        or not annotations
        or not isinstance(annotations[0], dict)
        or not isinstance(annotations[0].get("description"), str)
        or not isinstance(document_text, str)
    ):
        return False
    text_detection_digits = "".join(
        re.findall(r"\d", annotations[0]["description"])
    )
    document_digits = "".join(re.findall(r"\d", document_text))
    return bool(text_detection_digits and document_digits) and (
        text_detection_digits != document_digits
    )


def _call_google_vision(
    images: list[bytes],
    api_key: str,
    *,
    text_detection_first: bool = False,
) -> object | MeterOcrResult:
    url = f"{_GOOGLE_VISION_ENDPOINT}?{urlencode({'key': api_key})}"
    request_body = json.dumps(
        {
            "requests": [
                {
                    "image": {"content": base64.b64encode(image).decode("ascii")},
                    "features": (
                        [
                            {"type": "TEXT_DETECTION"},
                            {"type": "DOCUMENT_TEXT_DETECTION"},
                        ]
                        if text_detection_first and index == 0
                        else [{"type": "DOCUMENT_TEXT_DETECTION"}]
                    ),
                }
                for index, image in enumerate(images)
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
            return json.loads(response.read())
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


def _extract_google_vision_readings(
    content: bytes,
    api_key: str,
    lcd: PiusiLcdRecognition | None = None,
) -> MeterOcrResult:
    try:
        if (
            lcd is not None
            and lcd.display_found
            and lcd.display_crop is not None
            and lcd.current_row_crop is not None
            and lcd.total_row_crop is not None
        ):
            display_content = _prepare_google_vision_detected_image(
                lcd.display_crop,
                grayscale=False,
                min_width=_GOOGLE_VISION_MIN_WIDTH,
            )
            current_row_content = _prepare_google_vision_detected_image(
                lcd.current_row_crop,
                grayscale=True,
                min_width=_GOOGLE_VISION_CURRENT_ROW_MIN_WIDTH,
            )
            total_row_content = _prepare_google_vision_detected_image(
                lcd.total_row_crop,
                grayscale=True,
                min_width=_GOOGLE_VISION_TOTAL_ROW_MIN_WIDTH,
            )
        else:
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

    response_data = _call_google_vision(
        [display_content, current_row_content, total_row_content],
        api_key,
        text_detection_first=True,
    )
    if isinstance(response_data, MeterOcrResult):
        return response_data

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
    display_readings = _google_vision_response_lines(responses[0])
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
    current_readings = _google_vision_response_lines(current_response)
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
    total_error = total_response.get("error")
    total_document = total_response.get("fullTextAnnotation")
    total_readings = _google_vision_response_lines(total_response)
    if (
        (not total_readings or total_readings[0][2] < _GOOGLE_VISION_MIN_CONFIDENCE)
        and isinstance(display_document, dict)
    ):
        try:
            detected_row_content = _prepare_google_vision_detected_row_image(
                display_content,
                display_document,
            )
        except (OSError, ValueError, Image.DecompressionBombError):
            detected_row_content = None
        if detected_row_content is not None:
            detected_response_data = _call_google_vision(
                [detected_row_content],
                api_key,
            )
            if isinstance(detected_response_data, MeterOcrResult):
                return detected_response_data
            detected_responses = (
                detected_response_data.get("responses")
                if isinstance(detected_response_data, dict)
                else None
            )
            if (
                not isinstance(detected_responses, list)
                or not detected_responses
                or not isinstance(detected_responses[0], dict)
            ):
                return MeterOcrResult(
                    status="failed",
                    message="Google Vision returned no detected-row OCR response.",
                )
            detected_result = detected_responses[0]
            detected_error = detected_result.get("error")
            if isinstance(detected_error, dict):
                message = detected_error.get(
                    "message", "The OCR request was rejected."
                )
                return MeterOcrResult(
                    status="failed",
                    message=f"Google Vision error reading the detected TOTAL row: {message}",
                )
            detected_document = detected_result.get("fullTextAnnotation")
            detected_readings = _google_vision_response_lines(detected_result)
            if detected_readings and (
                not total_readings
                or detected_readings[0][2] > total_readings[0][2]
            ):
                total_readings = detected_readings

    if not total_readings:
        if isinstance(total_error, dict):
            message = total_error.get("message", "The OCR request was rejected.")
            return MeterOcrResult(
                status="failed",
                message=f"Google Vision error reading the cumulative row: {message}",
            )
        return MeterOcrResult(
            status="uncertain",
            current_fill_litres=display_result.current_fill_litres,
            current_fill_confidence=display_result.current_fill_confidence,
            message="Google Vision could not read the PIUSI TOTAL row. Retake the photo.",
        )

    _, current_text, current_confidence = current_reading
    _, total_text, total_confidence = total_readings[0]
    display_total = display_readings[1] if len(display_readings) > 1 else None
    display_total_digits = (
        _ascii_digits(display_total[1])
        if display_total is not None
        else None
    )
    total_digits = _ascii_digits(total_text)
    if (
        display_total_digits is not None
        and total_digits is not None
        and display_total_digits != total_digits
    ):
        current_raw_digits, _ = (
            _raw_digits_and_decimal_position(current_text)
        )
        return MeterOcrResult(
            status="uncertain",
            current_fill_litres=_whole_number_from_digits(current_raw_digits),
            cumulative_total_litres=_cumulative_total_litres_from_digits(total_digits),
            current_fill_confidence=current_confidence,
            cumulative_total_confidence=total_confidence,
            message=(
                "Google Vision read different PIUSI TOTAL values from the display "
                "and close-up. Retake the photo."
            ),
            current_fill_raw_digits=current_raw_digits,
            cumulative_total_raw_digits=total_digits,
        )

    result = parse_meter_ocr_data(
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
        },
        min_confidence=_GOOGLE_VISION_MIN_CONFIDENCE,
    )
    if (
        isinstance(display_document, dict)
        and _google_vision_text_detection_disagrees(
            responses[0], display_document
        )
    ):
        warning = (
            "Google Vision TEXT_DETECTION and DOCUMENT_TEXT_DETECTION disagree."
        )
        return replace(
            result,
            status="uncertain",
            message=warning,
            warnings=(warning,),
        )
    return result


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


def _total_ocr_result(
    text: str, confidence: float, provider: str
) -> MeterOcrResult:
    raw_digits, _ = _raw_digits_and_decimal_position(text)
    if raw_digits is None:
        return MeterOcrResult(
            status="uncertain",
            provider=provider,
            cumulative_total_confidence=confidence,
            message="Google Vision could not read the PIUSI TOTAL row.",
        )

    warnings = []
    if len(raw_digits) < 6:
        warnings.append(
            "The TOTAL-row OCR returned fewer than six digits; check for missing digits."
        )
    cumulative_total = Decimal(raw_digits).scaleb(-3)
    if confidence < _GOOGLE_VISION_MIN_CONFIDENCE:
        warnings.append("TOTAL-row OCR confidence is low; confirm every digit.")
    return MeterOcrResult(
        status="uncertain" if warnings else "ready",
        cumulative_total_litres=float(cumulative_total),
        cumulative_total_confidence=confidence,
        provider=provider,
        cumulative_total_raw_digits=raw_digits,
        cumulative_total_decimal_position=max(0, len(raw_digits) - 3),
        warnings=tuple(warnings),
        message="; ".join(warnings) if warnings else None,
    )


def _extract_google_vision_total(
    api_key: str, lcd: PiusiTotalRecognition
) -> MeterOcrResult:
    if not lcd.display_found or lcd.total_row_crop is None:
        return MeterOcrResult(
            status="uncertain",
            provider="google_vision",
            message="Could not locate the PIUSI TOTAL row; retake a closer photo.",
        )
    try:
        total_content = _prepare_google_vision_detected_image(
            lcd.total_row_crop,
            grayscale=True,
            min_width=_GOOGLE_VISION_TOTAL_ROW_MIN_WIDTH,
        )
    except (OSError, ValueError, Image.DecompressionBombError):
        return MeterOcrResult(
            status="failed",
            provider="google_vision",
            message="Could not prepare the PIUSI TOTAL row for Google Vision.",
        )

    response_data = _call_google_vision(
        [total_content],
        api_key,
        text_detection_first=True,
    )
    if isinstance(response_data, MeterOcrResult):
        return replace(response_data, provider="google_vision")
    responses = (
        response_data.get("responses")
        if isinstance(response_data, dict)
        else None
    )
    if (
        not isinstance(responses, list)
        or not responses
        or not isinstance(responses[0], dict)
    ):
        return MeterOcrResult(
            status="failed",
            provider="google_vision",
            message="Google Vision returned no TOTAL-row OCR response.",
        )

    response = responses[0]
    api_error = response.get("error")
    if isinstance(api_error, dict):
        message = api_error.get("message", "The OCR request was rejected.")
        return MeterOcrResult(
            status="failed",
            provider="google_vision",
            message=f"Google Vision error reading the TOTAL row: {message}",
        )

    readings = _google_vision_response_lines(response)
    if not readings:
        return MeterOcrResult(
            status="uncertain",
            provider="google_vision",
            message="Google Vision could not read the PIUSI TOTAL row.",
        )
    _, text, confidence = max(
        readings,
        key=lambda reading: (
            len(_raw_digits_and_decimal_position(reading[1])[0] or ""),
            reading[2],
        ),
    )
    result = _total_ocr_result(text, confidence, "google_vision")
    document = response.get("fullTextAnnotation")
    if isinstance(document, dict) and _google_vision_text_detection_disagrees(
        response, document
    ):
        warning = (
            "Google Vision TEXT_DETECTION and DOCUMENT_TEXT_DETECTION disagree on the TOTAL digits."
        )
        return replace(
            result,
            status="uncertain",
            message="; ".join(filter(None, (result.message, warning))),
            warnings=tuple(dict.fromkeys((*result.warnings, warning))),
        )
    return result


def _extract_tesseract_total(
    lcd: PiusiTotalRecognition,
) -> MeterOcrResult:
    try:
        import pytesseract
        from pytesseract import Output
        from pytesseract.pytesseract import TesseractError, TesseractNotFoundError
    except ModuleNotFoundError:
        return MeterOcrResult(
            status="unavailable",
            provider="tesseract",
            message="Install the local pytesseract package to enable meter OCR.",
        )
    if lcd.total_row_crop is None:
        return MeterOcrResult(
            status="uncertain",
            provider="tesseract",
            message="Could not locate the PIUSI TOTAL row.",
        )

    pytesseract.pytesseract.tesseract_cmd = _get_tesseract_command()
    try:
        with Image.open(BytesIO(lcd.total_row_crop)) as source:
            row = ImageOps.autocontrast(
                ImageOps.exif_transpose(source).convert("L"), cutoff=1
            )
        width, height = row.size
        scale = max(1, round(1600 / max(width, 1)))
        row = row.resize(
            (width * scale, height * scale),
            Image.Resampling.LANCZOS,
        )
        output = pytesseract.image_to_data(
            row,
            config="--psm 7 -c tessedit_char_whitelist=0123456789",
            output_type=Output.DICT,
        )
    except TesseractNotFoundError:
        return MeterOcrResult(
            status="unavailable",
            provider="tesseract",
            message="The local Tesseract executable is not installed or is not on PATH.",
        )
    except TesseractError as error:
        return MeterOcrResult(
            status="failed",
            provider="tesseract",
            message=f"Local Tesseract OCR failed: {error}",
        )

    words = [
        (str(text).strip(), float(confidence))
        for text, confidence in zip(output.get("text", []), output.get("conf", []))
        if str(text).strip() and str(text).strip().isdigit()
    ]
    if not words:
        return MeterOcrResult(
            status="uncertain",
            provider="tesseract",
            message="Tesseract could not read the PIUSI TOTAL row.",
        )
    text = "".join(word for word, _ in words)
    confidence = sum(score for _, score in words) / len(words)
    return _total_ocr_result(text, confidence, "tesseract")


def _apply_piusi_total_evidence(
    result: MeterOcrResult,
    lcd: PiusiTotalRecognition,
    provider: str,
) -> MeterOcrResult:
    warnings = list(result.warnings) + list(lcd.warnings)
    if not lcd.display_found:
        return replace(
            result,
            status="uncertain",
            provider=provider,
            message="Could not locate the PIUSI display; retake a closer photo.",
            warnings=tuple(dict.fromkeys(warnings)),
        )

    vision_digits = result.cumulative_total_raw_digits
    segment = lcd.cumulative_total
    chosen_digits = vision_digits or segment.raw_digits
    if vision_digits is None and segment.raw_digits is not None:
        warnings.append(
            "Google Vision did not return TOTAL digits; the OpenCV candidate needs manual confirmation."
        )
    if segment.raw_digits is None:
        warnings.append("OpenCV could not verify all TOTAL-row digits.")
    elif vision_digits is not None and vision_digits != segment.raw_digits:
        warnings.append(
            "Google Vision and OpenCV disagree on the TOTAL-row digits; manual review is required."
        )
    if chosen_digits is not None and len(chosen_digits) < 6:
        warnings.append(
            "The TOTAL reading has fewer than six digits; check for missing digits."
        )
    if chosen_digits is not None and len(chosen_digits) > 18:
        warnings.append("The TOTAL reading has extra or unsupported digits.")
        chosen_digits = None

    chosen_value = (
        Decimal(chosen_digits).scaleb(-3)
        if chosen_digits is not None
        else None
    )
    confidence = (
        result.cumulative_total_confidence
        if vision_digits is not None
        else None
    )
    if segment.raw_digits is not None and segment.confidence is not None:
        if segment.confidence < 0.55:
            warnings.append("OpenCV TOTAL-row confidence is low.")
    if vision_digits is None and segment.raw_digits is None:
        warnings.append("No TOTAL-row digits could be read.")

    warnings = list(dict.fromkeys(warnings))
    ready = (
        vision_digits is not None
        and segment.raw_digits == vision_digits
        and len(vision_digits) >= 6
        and len(vision_digits) <= 18
        and (confidence or 0) >= _GOOGLE_VISION_MIN_CONFIDENCE
        and (segment.confidence or 0) >= 0.55
        and not warnings
    )
    message = "; ".join(warnings) if warnings else result.message
    return MeterOcrResult(
        status=(
            "ready"
            if ready
            else result.status
            if result.status in {"failed", "unavailable"}
            else "uncertain"
        ),
        cumulative_total_litres=(
            float(chosen_value) if chosen_value is not None else None
        ),
        cumulative_total_confidence=confidence,
        message=message,
        provider=provider,
        cumulative_total_raw_digits=chosen_digits,
        cumulative_total_decimal_position=(
            max(0, len(chosen_digits) - 3)
            if chosen_digits is not None
            else None
        ),
        cumulative_total_segment_confidence=(
            segment.confidence * 100 if segment.confidence is not None else None
        ),
        warnings=tuple(warnings),
    )


def _apply_piusi_evidence(
    result: MeterOcrResult,
    lcd: PiusiLcdRecognition,
    provider: str,
) -> MeterOcrResult:
    current = lcd.current_fill
    total = lcd.cumulative_total
    warnings = list(result.warnings) + list(lcd.warnings)

    if result.status in {"failed", "unavailable"}:
        return replace(
            result,
            provider=provider,
            current_fill_raw_digits=current.raw_digits,
            current_fill_decimal_position=current.decimal_position,
            cumulative_total_raw_digits=total.raw_digits,
            cumulative_total_decimal_position=total.decimal_position,
            current_fill_segment_confidence=(
                current.confidence * 100 if current.confidence is not None else None
            ),
            cumulative_total_segment_confidence=(
                total.confidence * 100 if total.confidence is not None else None
            ),
            warnings=tuple(warnings),
        )

    if not lcd.display_found:
        return MeterOcrResult(
            status="uncertain",
            message="Could not locate the PIUSI display; retake a closer photo.",
            provider=provider,
            warnings=tuple(warnings),
        )

    for row_name, vision_digits, segment_row in (
        ("current-fill", result.current_fill_raw_digits, current),
        ("cumulative-total", result.cumulative_total_raw_digits, total),
    ):
        if segment_row.raw_digits is None:
            continue
        if vision_digits is None:
            warnings.append(
                f"Google Vision did not provide raw {row_name} digits for comparison."
            )
        elif vision_digits != segment_row.raw_digits:
            warnings.append(
                f"Google Vision and seven-segment recognition disagree on the {row_name} digits."
            )
    current_digits_match = (
        current.raw_digits is not None
        and current.raw_digits == result.current_fill_raw_digits
    )
    total_digits_match = (
        total.raw_digits is not None
        and total.raw_digits == result.cumulative_total_raw_digits
    )
    current_digits = (
        result.current_fill_raw_digits
        if current.raw_digits is None
        else (
            current.raw_digits
            if (current.confidence or 0) >= 0.65
            or current.raw_digits == result.current_fill_raw_digits
            else None
        )
    )
    total_digits = (
        result.cumulative_total_raw_digits
        if total.raw_digits is None
        else (
            total.raw_digits
            if (total.confidence or 0) >= 0.65
            or total.raw_digits == result.cumulative_total_raw_digits
            else None
        )
    )
    current_value = _whole_number_from_digits(current_digits)
    total_value = _cumulative_total_litres_from_digits(total_digits)
    if not current_digits_match or not total_digits_match:
        if not current_digits_match:
            warnings.append("The current-fill digits need manual review.")
        if not total_digits_match:
            warnings.append("The cumulative-total digits need manual review.")

    warnings = list(dict.fromkeys(warnings))
    message = "; ".join(warnings) if warnings else result.message
    status = result.status
    if warnings or current_value is None or total_value is None:
        status = "uncertain"
    elif (
        (current.confidence or 0) < 0.65
        or (total.confidence or 0) < 0.65
    ):
        status = "uncertain"
        message = "Seven-segment confidence is low. Review both readings manually."
        warnings.append(message)

    return MeterOcrResult(
        status=status,
        current_fill_litres=current_value,
        cumulative_total_litres=total_value,
        current_fill_confidence=result.current_fill_confidence,
        cumulative_total_confidence=result.cumulative_total_confidence,
        message=message,
        provider=provider,
        current_fill_raw_digits=current.raw_digits,
        current_fill_decimal_position=(
            max(0, len(current.raw_digits) - 3)
            if current.raw_digits is not None
            else None
        ),
        cumulative_total_raw_digits=total.raw_digits,
        cumulative_total_decimal_position=(
            max(0, len(total.raw_digits) - 3)
            if total.raw_digits is not None
            else None
        ),
        current_fill_segment_confidence=(
            current.confidence * 100 if current.confidence is not None else None
        ),
        cumulative_total_segment_confidence=(
            total.confidence * 100 if total.confidence is not None else None
        ),
        warnings=tuple(warnings),
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
    if provider not in {"google_vision", "tesseract"}:
        return MeterOcrResult(
            status="failed",
            provider=provider,
            message=f"Unsupported OCR provider: {provider}.",
        )
    if provider == "google_vision" and not vision_api_key:
        return MeterOcrResult(
            status="unavailable",
            provider=provider,
            message=(
                "Google Vision is selected, but "
                "GOOGLE_CLOUD_VISION_API_KEY is not configured."
            ),
        )
    try:
        lcd = recognize_piusi_total(content)
    except (
        OSError,
        ValueError,
        Image.DecompressionBombError,
        cv2.error,
    ) as error:
        return MeterOcrResult(
            status="failed",
            provider=provider,
            message=f"Could not process the uploaded meter photo: {error}",
        )
    if provider == "google_vision":
        result = _extract_google_vision_total(vision_api_key, lcd)
    else:
        result = _extract_tesseract_total(lcd)
    return _apply_piusi_total_evidence(result, lcd, provider)
