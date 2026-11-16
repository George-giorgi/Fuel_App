from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from io import BytesIO

import cv2
import numpy as np
from PIL import Image, ImageOps


_LCD_HSV_LOW = np.array([40, 35, 140], dtype=np.uint8)
_LCD_HSV_HIGH = np.array([90, 180, 255], dtype=np.uint8)
_SEGMENT_HSV_LOW = np.array([90, 35, 0], dtype=np.uint8)
_SEGMENT_HSV_HIGH = np.array([140, 255, 190], dtype=np.uint8)
_SEGMENTS_BY_DIGIT = {
    "0": "abcdef",
    "1": "bc",
    "2": "abged",
    "3": "abgcd",
    "4": "fgbc",
    "5": "afgcd",
    "6": "afgecd",
    "7": "abc",
    "8": "abcdefg",
    "9": "abfgcd",
}
_SEGMENT_REGIONS = {
    "a": (0.25, 0.03, 0.75, 0.22),
    "b": (0.67, 0.14, 0.95, 0.46),
    "c": (0.67, 0.54, 0.95, 0.86),
    "d": (0.25, 0.78, 0.75, 0.97),
    "e": (0.05, 0.54, 0.33, 0.86),
    "f": (0.05, 0.14, 0.33, 0.46),
    "g": (0.25, 0.42, 0.75, 0.60),
}


@dataclass(frozen=True)
class LcdRowReading:
    raw_digits: str | None
    decimal_position: int | None
    value: Decimal | None
    confidence: float | None


@dataclass(frozen=True)
class PiusiLcdRecognition:
    display_found: bool
    current_fill: LcdRowReading
    cumulative_total: LcdRowReading
    display_crop: bytes | None
    current_row_crop: bytes | None
    total_row_crop: bytes | None
    warnings: tuple[str, ...] = ()


def _encode_jpeg(image: np.ndarray) -> bytes:
    success, encoded = cv2.imencode(
        ".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 96]
    )
    if not success:
        raise ValueError("Could not encode the detected PIUSI display.")
    return encoded.tobytes()


def _load_oriented_image(content: bytes) -> np.ndarray:
    with Image.open(BytesIO(content)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)


def _lcd_candidate(image: np.ndarray) -> np.ndarray | None:
    height, width = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, _LCD_HSV_LOW, _LCD_HSV_HIGH)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (17, 13))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(
        mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    candidates = []
    image_area = height * width
    for contour in contours:
        x, y, box_width, box_height = cv2.boundingRect(contour)
        area = cv2.contourArea(contour)
        aspect = box_width / max(box_height, 1)
        if (
            area < image_area * 0.015
            or box_width < width * 0.18
            or box_height < height * 0.08
            or not 1.0 <= aspect <= 2.4
        ):
            continue
        rectangularity = area / max(box_width * box_height, 1)
        center_x = (x + box_width / 2) / width
        center_y = (y + box_height / 2) / height
        center_score = max(0.0, 1.0 - abs(center_x - 0.5) - abs(center_y - 0.55))
        score = area * rectangularity * (0.65 + center_score)
        candidates.append((score, contour))
    if not candidates:
        return None

    _, contour = max(candidates, key=lambda item: item[0])
    rect = cv2.minAreaRect(contour)
    points = cv2.boxPoints(rect).astype(np.float32)
    sums = points.sum(axis=1)
    differences = np.diff(points, axis=1).reshape(-1)
    corners = np.array(
        [
            points[np.argmin(sums)],
            points[np.argmin(differences)],
            points[np.argmax(sums)],
            points[np.argmax(differences)],
        ],
        dtype=np.float32,
    )
    top_left, top_right, bottom_right, bottom_left = corners
    target_width = max(
        int(np.linalg.norm(top_right - top_left)),
        int(np.linalg.norm(bottom_right - bottom_left)),
    )
    target_height = max(
        int(np.linalg.norm(bottom_left - top_left)),
        int(np.linalg.norm(bottom_right - top_right)),
    )
    if target_width < 80 or target_height < 50:
        return None
    destination = np.array(
        [
            [0, 0],
            [target_width - 1, 0],
            [target_width - 1, target_height - 1],
            [0, target_height - 1],
        ],
        dtype=np.float32,
    )
    transform = cv2.getPerspectiveTransform(corners, destination)
    return cv2.warpPerspective(image, transform, (target_width, target_height))


def _group_components(
    mask: np.ndarray,
    offset_x: int,
    offset_y: int,
    *,
    minimum_area: int,
) -> list[tuple[int, int, int, int]]:
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    boxes = [
        [int(x + offset_x), int(y + offset_y), int(width), int(height)]
        for x, y, width, height, area in stats[1:count]
        if area >= minimum_area and width >= 4 and height >= 8
    ]
    changed = True
    while changed:
        changed = False
        for index, first in enumerate(boxes):
            x1, y1, width1, height1 = first
            for other_index in range(index + 1, len(boxes)):
                x2, y2, width2, height2 = boxes[other_index]
                overlap = min(x1 + width1, x2 + width2) - max(x1, x2)
                vertical_gap = max(
                    0, max(y1, y2) - min(y1 + height1, y2 + height2)
                )
                if overlap > 0 and vertical_gap <= 12:
                    left = min(x1, x2)
                    top = min(y1, y2)
                    right = max(x1 + width1, x2 + width2)
                    bottom = max(y1 + height1, y2 + height2)
                    boxes[index] = [left, top, right - left, bottom - top]
                    boxes.pop(other_index)
                    changed = True
                    break
            if changed:
                break
    return sorted(
        (tuple(box) for box in boxes),
        key=lambda box: box[0],
    )


def _split_wide_glyphs(
    boxes: list[tuple[int, int, int, int]],
) -> list[tuple[int, int, int, int]]:
    normal_widths = [
        width
        for _, _, width, height in boxes
        if height > 0 and 0.32 <= width / height <= 0.65
    ]
    if not normal_widths:
        return boxes
    typical_width = float(np.median(normal_widths))
    result = []
    for x, y, width, height in boxes:
        pieces = round(width / typical_width)
        if pieces > 1 and width / max(height, 1) > 0.72:
            piece_width = width / pieces
            result.extend(
                (
                    round(x + piece_width * index),
                    y,
                    round(piece_width),
                    height,
                )
                for index in range(pieces)
            )
        else:
            result.append((x, y, width, height))
    return result


def _glyph_occupancy(
    mask: np.ndarray,
    box: tuple[int, int, int, int],
    offset_x: int,
    offset_y: int,
) -> dict[str, float]:
    x, y, width, height = box
    x -= offset_x
    y -= offset_y
    glyph = mask[y : y + height, x : x + width]
    if width / max(height, 1) < 0.35:
        padded_width = max(width, round(height * 0.55))
        canvas = np.zeros((height, padded_width), dtype=np.uint8)
        left = max(0, padded_width - width)
        canvas[:, left : left + width] = glyph
        glyph = canvas
    normalized = cv2.resize(
        glyph, (100, 140), interpolation=cv2.INTER_NEAREST
    ) > 0
    occupancy = {}
    for segment, (left, top, right, bottom) in _SEGMENT_REGIONS.items():
        region = normalized[
            round(top * 140) : round(bottom * 140),
            round(left * 100) : round(right * 100),
        ]
        occupancy[segment] = float(region.mean())
    return occupancy


def _classify_glyph(
    mask: np.ndarray,
    box: tuple[int, int, int, int],
    offset_x: int,
    offset_y: int,
    segment_threshold: float,
) -> tuple[str | None, float]:
    _, _, width, height = box
    if width / max(height, 1) < 0.31:
        return "1", 0.72
    occupancy = _glyph_occupancy(mask, box, offset_x, offset_y)
    active = {
        segment
        for segment, fraction in occupancy.items()
        if fraction >= segment_threshold
    }
    distances = {
        digit: len(active ^ set(pattern))
        / max(len(active | set(pattern)), 1)
        for digit, pattern in _SEGMENTS_BY_DIGIT.items()
    }
    digit = min(distances, key=distances.get)
    confidence = max(0.0, 1.0 - distances[digit])
    if distances[digit] > 0.45:
        return None, confidence
    return digit, confidence


def _decimal_position(
    mask: np.ndarray,
    boxes: list[tuple[int, int, int, int]],
    offset_x: int,
    offset_y: int,
    row_height: int,
) -> int | None:
    if len(boxes) < 2:
        return None
    digit_width = float(np.median([box[2] for box in boxes]))
    digit_bottom = float(np.median([box[1] + box[3] for box in boxes]))
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    candidates = []
    for x, y, width, height, area in stats[1:count]:
        if (
            area < 3
            or area > 36
            or width > max(4, digit_width * 0.22)
            or height > max(4, row_height * 0.13)
        ):
            continue
        center_x = x + offset_x + width / 2
        center_y = y + offset_y + height / 2
        if center_y < digit_bottom - row_height * 0.12:
            continue
        for index, (first, second) in enumerate(zip(boxes, boxes[1:])):
            if first[0] + first[2] < center_x < second[0]:
                candidates.append((index + 1, area))
    if len(candidates) != 1:
        return None
    return candidates[0][0]


def _recognize_row(
    display: np.ndarray,
    bounds: tuple[float, float, float, float],
    *,
    minimum_digits: int,
    split_wide_glyphs: bool,
    segment_threshold: float,
) -> LcdRowReading:
    height, width = display.shape[:2]
    left, top, right, bottom = bounds
    x1, y1 = round(width * left), round(height * top)
    x2, y2 = round(width * right), round(height * bottom)
    row = display[y1:y2, x1:x2]
    if row.size == 0:
        return LcdRowReading(None, None, None, None)

    hsv = cv2.cvtColor(row, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, _SEGMENT_HSV_LOW, _SEGMENT_HSV_HIGH)
    boxes = _group_components(
        mask, x1, y1, minimum_area=max(18, round(row.size * 0.0007))
    )
    row_height = y2 - y1
    if split_wide_glyphs:
        boxes = _split_wide_glyphs(boxes)
    boxes = [
        box
        for box in boxes
        if box[3] >= row_height * 0.38
        and 0.12 <= box[2] / max(box[3], 1) <= 1.05
        and box[0] + box[2] <= x2
    ]
    boxes.sort(key=lambda box: box[0])
    classified = [
        _classify_glyph(mask, box, x1, y1, segment_threshold)
        for box in boxes
    ]
    if len(classified) < minimum_digits or any(digit is None for digit, _ in classified):
        return LcdRowReading(None, None, None, None)

    raw_digits = "".join(digit for digit, _ in classified if digit is not None)
    confidence = sum(score for _, score in classified) / len(classified)
    decimal_position = _decimal_position(
        mask,
        boxes,
        x1,
        y1,
        row_height,
    )
    value = None
    if decimal_position is not None and 0 < decimal_position < len(raw_digits):
        try:
            value = Decimal(
                f"{raw_digits[:decimal_position]}.{raw_digits[decimal_position:]}"
            )
        except InvalidOperation:
            value = None
    return LcdRowReading(raw_digits, decimal_position, value, confidence)


def recognize_piusi_lcd(content: bytes) -> PiusiLcdRecognition:
    image = _load_oriented_image(content)
    display = _lcd_candidate(image)
    if display is None:
        missing = LcdRowReading(None, None, None, None)
        return PiusiLcdRecognition(
            False,
            missing,
            missing,
            None,
            None,
            None,
            ("Could not locate the PIUSI LCD display.",),
        )

    display_height, display_width = display.shape[:2]
    current_row = display[
        round(display_height * 0.02) : round(display_height * 0.55),
        round(display_width * 0.02) : round(display_width * 0.95),
    ]
    total_row = display[
        round(display_height * 0.65) : round(display_height * 0.96),
        round(display_width * 0.15) : round(display_width * 0.95),
    ]
    current = _recognize_row(
        display,
        (0.02, 0.02, 0.95, 0.55),
        minimum_digits=3,
        split_wide_glyphs=False,
        segment_threshold=0.35,
    )
    total = _recognize_row(
        display,
        (0.15, 0.65, 0.95, 0.96),
        minimum_digits=4,
        split_wide_glyphs=True,
        segment_threshold=0.45,
    )
    warnings = []
    if current.raw_digits is None:
        warnings.append("Seven-segment recognition could not read the top row.")
    if total.raw_digits is None:
        warnings.append("Seven-segment recognition could not read the TOTAL row.")
    if current.decimal_position is None:
        warnings.append("The current-fill decimal point is uncertain.")
    if total.decimal_position is None:
        warnings.append("The cumulative-total decimal point is uncertain.")
    return PiusiLcdRecognition(
        True,
        current,
        total,
        _encode_jpeg(display),
        _encode_jpeg(current_row),
        _encode_jpeg(total_row),
        tuple(warnings),
    )
