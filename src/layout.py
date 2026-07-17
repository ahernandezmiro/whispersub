"""Pure role classification and conservative ASS layout planning."""

from bisect import bisect_left
from dataclasses import dataclass
from enum import Enum
import math
import os
import re
from typing import Optional
import unicodedata


_OVERRIDE_BLOCK = re.compile(r"\{[^}]*\}")
_ALIGNMENT_TAG = re.compile(r"\\an([1-9])")
_POSITION_TAG = re.compile(r"\\pos\(\s*([-+\d.]+)\s*,\s*([-+\d.]+)\s*\)")
_MOVE_TAG = re.compile(
    r"\\move\(\s*([-+\d.]+)\s*,\s*([-+\d.]+)\s*,"
    r"\s*([-+\d.]+)\s*,\s*([-+\d.]+)"
)
_DRAWING_TAG = re.compile(r"\\p[1-9]\d*")


class EventRole(str, Enum):
    DIALOGUE = "dialogue"
    OVERLAY = "overlay"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class TextExtent:
    width: float
    height: float
    lines: int


@dataclass(frozen=True)
class Rect:
    left: float
    top: float
    right: float
    bottom: float

    @property
    def width(self):
        return max(0.0, self.right - self.left)

    @property
    def height(self):
        return max(0.0, self.bottom - self.top)

    def intersection_area(self, other):
        width = max(0.0, min(self.right, other.right) - max(self.left, other.left))
        height = max(0.0, min(self.bottom, other.bottom) - max(self.top, other.top))
        return width * height

    def union(self, other):
        return Rect(
            min(self.left, other.left),
            min(self.top, other.top),
            max(self.right, other.right),
            max(self.bottom, other.bottom),
        )

    def clipped(self, width, height):
        return Rect(
            max(0.0, min(width, self.left)),
            max(0.0, min(height, self.top)),
            max(0.0, min(width, self.right)),
            max(0.0, min(height, self.bottom)),
        )


@dataclass(frozen=True)
class LayoutEvent:
    start: int
    end: int
    text: str
    style: object
    role: EventRole
    layer: int = 0
    marginl: int = 0
    marginr: int = 0
    marginv: int = 0


@dataclass(frozen=True)
class LayoutPlan:
    zone: str
    alignment: int
    transcription_marginv: int
    romanization_marginv: Optional[int]
    transcription_fontsize: float
    romanization_fontsize: Optional[float]
    transcription_box: Rect
    romanization_box: Optional[Rect]


def classify_event_role(text, style_name="", alignment=2, positioned=False, effect=""):
    """Classify rendering behavior without making semantic guesses authoritative."""
    normalized_style = style_name.lower().replace("-", "_").replace(" ", "_")
    style_tokens = set(filter(None, normalized_style.split('_')))
    lowered_effect = (effect or "").lower()
    if (
        positioned
        or _POSITION_TAG.search(text)
        or _MOVE_TAG.search(text)
        or _DRAWING_TAG.search(text)
        or lowered_effect
    ):
        return EventRole.OVERLAY

    overlay_markers = (
        "sign", "title", "eyecatch", "on_screen", "onscreen", "logo",
        "caption", "episode", "preview", "credit", "opening", "ending",
        "op_", "ed_", "song", "karaoke", "lyrics", "insert", "typeset",
    )
    if (
        any(marker in normalized_style for marker in overlay_markers)
        or style_tokens.intersection({'op', 'ed'})
    ):
        return EventRole.OVERLAY

    dialogue_markers = (
        "main", "dialogue", "default", "flashback", "narration", "italics",
        "transcription", "secondary", "speech", "spoken",
    )
    if any(marker in normalized_style for marker in dialogue_markers):
        return EventRole.DIALOGUE

    # Unmarked bottom-aligned, normally timed cues are generally dialogue. Top and
    # middle cues are left unknown unless their style explicitly identifies speech.
    if alignment in (1, 2, 3):
        return EventRole.DIALOGUE
    return EventRole.UNKNOWN


def _style_number(style, name, default):
    value = getattr(style, name, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _clean_text(text):
    return _OVERRIDE_BLOCK.sub("", text).replace("\\h", " ")


class FallbackTextMeasurer:
    """Deterministic conservative estimator used when exact font metrics are absent."""

    def _character_width(self, character, font_size):
        if character.isspace():
            factor = 0.36
        elif unicodedata.east_asian_width(character) in ("W", "F"):
            factor = 1.0
        elif character.isupper():
            factor = 0.68
        elif character.islower() or character.isdigit():
            factor = 0.58
        else:
            factor = 0.62
        return font_size * factor

    def measure(self, text, style, max_width):
        font_size = max(1.0, _style_number(style, "fontsize", 16))
        scale_x = max(0.1, _style_number(style, "scalex", 100) / 100)
        scale_y = max(0.1, _style_number(style, "scaley", 100) / 100)
        spacing = _style_number(style, "spacing", 0)
        max_width = max(font_size, float(max_width))
        explicit_lines = re.split(r"\\N|\\n|\n", _clean_text(text))
        rendered_width = 0.0
        rendered_lines = 0
        for line in explicit_lines or [""]:
            line_width = sum(
                self._character_width(character, font_size) * scale_x + spacing
                for character in line
            )
            wrapped_lines = max(1, math.ceil(line_width / max_width))
            rendered_lines += wrapped_lines
            rendered_width = max(rendered_width, min(max_width, line_width))
        outline = max(0.0, _style_number(style, "outline", 1))
        shadow = max(0.0, _style_number(style, "shadow", 1))
        line_height = font_size * scale_y * 1.28
        padding = 2 * outline + shadow
        return TextExtent(
            min(max_width, rendered_width + padding),
            rendered_lines * line_height + padding,
            rendered_lines,
        )


class FontAwareTextMeasurer:
    """Use locally resolved font metrics when Pillow is available, else fall back."""

    def __init__(self, fallback=None):
        self.fallback = fallback or FallbackTextMeasurer()
        self._fonts = {}
        self._measurements = {}
        self._font_files = None
        try:
            from PIL import ImageFont
        except ImportError:
            ImageFont = None
        self._image_font = ImageFont

    def _available_font_files(self):
        if self._font_files is not None:
            return self._font_files
        directories = []
        windows_directory = os.environ.get('WINDIR')
        if windows_directory:
            directories.append(os.path.join(windows_directory, 'Fonts'))
        directories.extend([
            '/usr/share/fonts',
            '/usr/local/share/fonts',
            os.path.expanduser('~/.fonts'),
        ])
        files = []
        for directory in directories:
            if not os.path.isdir(directory):
                continue
            try:
                for root, child_directories, names in os.walk(directory):
                    child_directories.sort()
                    for name in sorted(names):
                        if name.lower().endswith(('.ttf', '.otf', '.ttc')):
                            files.append(os.path.join(root, name))
            except OSError:
                continue
        self._font_files = tuple(files)
        return self._font_files

    def _resolve(self, font_name, font_size):
        if self._image_font is None:
            return None
        key = (str(font_name).casefold(), round(font_size))
        if key in self._fonts:
            return self._fonts[key]
        size = max(1, round(font_size))
        candidates = [str(font_name)]
        normalized = re.sub(r'[^a-z0-9]', '', str(font_name).casefold())
        if not normalized:
            self._fonts[key] = None
            return None
        for path in self._available_font_files():
            stem = os.path.splitext(os.path.basename(path))[0]
            normalized_stem = re.sub(r'[^a-z0-9]', '', stem.casefold())
            if normalized_stem == normalized or normalized_stem.startswith(normalized):
                candidates.append(path)
        font = None
        for candidate in candidates:
            try:
                font = self._image_font.truetype(candidate, size=size)
                break
            except (OSError, TypeError, ValueError):
                continue
        self._fonts[key] = font
        return font

    def measure(self, text, style, max_width):
        font_size = max(1.0, _style_number(style, 'fontsize', 16))
        measurement_key = (
            text,
            getattr(style, 'fontname', ''),
            font_size,
            _style_number(style, 'scalex', 100),
            _style_number(style, 'scaley', 100),
            _style_number(style, 'spacing', 0),
            _style_number(style, 'outline', 1),
            _style_number(style, 'shadow', 1),
            float(max_width),
        )
        if measurement_key in self._measurements:
            return self._measurements[measurement_key]
        font = self._resolve(getattr(style, 'fontname', ''), font_size)
        if font is None:
            result = self.fallback.measure(text, style, max_width)
            self._measurements[measurement_key] = result
            return result
        scale_x = max(0.1, _style_number(style, 'scalex', 100) / 100)
        scale_y = max(0.1, _style_number(style, 'scaley', 100) / 100)
        spacing = _style_number(style, 'spacing', 0)
        max_width = max(font_size, float(max_width))
        explicit_lines = re.split(r'\\N|\\n|\n', _clean_text(text))
        rendered_width = 0.0
        rendered_lines = 0
        try:
            for line in explicit_lines or ['']:
                if hasattr(font, 'getlength'):
                    line_width = float(font.getlength(line)) * scale_x
                else:
                    line_bbox = font.getbbox(line or ' ')
                    line_width = float(line_bbox[2] - line_bbox[0]) * scale_x
                line_width += max(0, len(line) - 1) * spacing
                rendered_lines += max(1, math.ceil(line_width / max_width))
                rendered_width = max(rendered_width, min(max_width, line_width))
            bbox = font.getbbox('Ag')
        except (AttributeError, OSError, TypeError, ValueError):
            result = self.fallback.measure(text, style, max_width)
            self._measurements[measurement_key] = result
            return result
        line_height = max(font_size, bbox[3] - bbox[1]) * scale_y * 1.2
        outline = max(0.0, _style_number(style, 'outline', 1))
        shadow = max(0.0, _style_number(style, 'shadow', 1))
        padding = 2 * outline + shadow
        result = TextExtent(
            min(max_width, rendered_width + padding),
            rendered_lines * line_height + padding,
            rendered_lines,
        )
        self._measurements[measurement_key] = result
        return result


def _alignment_for(text, style):
    match = _ALIGNMENT_TAG.search(text)
    if match:
        return int(match.group(1))
    return int(_style_number(style, "alignment", 2))


def _anchored_rect(x, y, extent, alignment):
    column = (alignment - 1) % 3
    row = (alignment - 1) // 3
    if column == 0:
        left = x
    elif column == 1:
        left = x - extent.width / 2
    else:
        left = x - extent.width
    if row == 0:
        top = y - extent.height
    elif row == 1:
        top = y - extent.height / 2
    else:
        top = y
    return Rect(left, top, left + extent.width, top + extent.height)


def estimate_event_box(event, play_res_x, play_res_y, measurer=None):
    """Estimate a conservative screen-space box for a source ASS event."""
    measurer = measurer or FontAwareTextMeasurer()
    style = event.style
    marginl = event.marginl or int(_style_number(style, "marginl", 10))
    marginr = event.marginr or int(_style_number(style, "marginr", 10))
    marginv = event.marginv or int(_style_number(style, "marginv", 10))
    max_width = max(1, play_res_x - marginl - marginr)
    try:
        extent = measurer.measure(event.text, style, max_width)
    except Exception:
        extent = FallbackTextMeasurer().measure(event.text, style, max_width)
    alignment = _alignment_for(event.text, style)

    position = _POSITION_TAG.search(event.text)
    movement = _MOVE_TAG.search(event.text)
    if position:
        rect = _anchored_rect(float(position.group(1)), float(position.group(2)), extent, alignment)
    elif movement:
        start_rect = _anchored_rect(
            float(movement.group(1)), float(movement.group(2)), extent, alignment
        )
        end_rect = _anchored_rect(
            float(movement.group(3)), float(movement.group(4)), extent, alignment
        )
        rect = start_rect.union(end_rect)
    else:
        column = (alignment - 1) % 3
        row = (alignment - 1) // 3
        x = (marginl if column == 0 else play_res_x / 2 if column == 1 else play_res_x - marginr)
        y = (play_res_y - marginv if row == 0 else play_res_y / 2 if row == 1 else marginv)
        rect = _anchored_rect(x, y, extent, alignment)
    return rect.clipped(play_res_x, play_res_y)


class ObstacleIndex:
    """Interval index with cached geometry for source events."""

    def __init__(self, events, play_res_x, play_res_y, measurer=None):
        measurer = measurer or FontAwareTextMeasurer()
        entries = sorted(
            ((event.start, event.end, estimate_event_box(
                event, play_res_x, play_res_y, measurer
            )) for event in events),
            key=lambda entry: (entry[0], entry[1]),
        )
        self._entries = entries
        self._starts = [entry[0] for entry in entries]
        self._prefix_max_end = []
        latest_end = -1
        for _, end, _ in entries:
            latest_end = max(latest_end, end)
            self._prefix_max_end.append(latest_end)

    def query(self, start, end):
        position = bisect_left(self._starts, end) - 1
        matches = []
        while position >= 0 and self._prefix_max_end[position] > start:
            event_start, event_end, box = self._entries[position]
            if event_start < end and event_end > start:
                matches.append(box)
            position -= 1
        return tuple(matches)


def _copy_with_fontsize(style, font_size):
    measured_style = style.copy()
    measured_style.fontsize = font_size
    return measured_style


def _centered_box(top, extent, play_res_x, safe_x):
    width = min(extent.width, play_res_x - 2 * safe_x)
    left = max(safe_x, (play_res_x - width) / 2)
    return Rect(left, top, left + width, top + extent.height)


def plan_generated_layout(
    transcription_text,
    transcription_style,
    romanization_text,
    romanization_style,
    obstacles,
    play_res_x,
    play_res_y,
    preferred_zone="bottom",
    measurer=None,
):
    """Choose a stable top/bottom lane and return serialization-ready properties."""
    measurer = measurer or FontAwareTextMeasurer()
    safe_x = min(
        max(12, round(play_res_x * 0.035)),
        max(0, play_res_x // 2 - 1),
    )
    safe_y = min(
        max(12, round(play_res_y * 0.035)),
        max(0, play_res_y // 2 - 1),
    )
    padding = max(6, round(play_res_y * 0.012)) if romanization_text else 0
    available_width = max(1, play_res_x - 2 * safe_x)
    available_height = max(1, play_res_y - 2 * safe_y)
    fallback_measurer = FallbackTextMeasurer()

    def measure(text, style):
        try:
            return measurer.measure(text, style, available_width)
        except Exception:
            return fallback_measurer.measure(text, style, available_width)

    trans_font = _style_number(transcription_style, "fontsize", 16)
    rom_font = (
        _style_number(romanization_style, "fontsize", 12)
        if romanization_text and romanization_style else None
    )

    def measure_tracks():
        trans_extent = measure(
            transcription_text,
            _copy_with_fontsize(transcription_style, trans_font),
        )
        rom_extent = None
        if romanization_text and romanization_style and rom_font is not None:
            rom_extent = measure(
                romanization_text,
                _copy_with_fontsize(romanization_style, rom_font),
            )
        return trans_extent, rom_extent

    trans_extent, rom_extent = measure_tracks()
    total_height = trans_extent.height + (rom_extent.height + padding if rom_extent else 0)
    for _ in range(8):
        if total_height <= available_height:
            break
        scale = max(0.05, available_height / total_height * 0.98)
        trans_font = max(0.5, trans_font * scale)
        if rom_font is not None:
            rom_font = max(0.5, rom_font * scale)
        trans_extent, rom_extent = measure_tracks()
        total_height = (
            trans_extent.height + (rom_extent.height + padding if rom_extent else 0)
        )

    lowest_top = safe_y
    highest_top = max(safe_y, play_res_y - safe_y - total_height)
    step = max(2, round(play_res_y / 180))
    tops = list(range(round(lowest_top), round(highest_top) + 1, step))
    if round(highest_top) not in tops:
        tops.append(round(highest_top))
    preferred_zone = "top" if preferred_zone == "top" else "bottom"
    trans_preferred_margin = _style_number(
        transcription_style, 'marginv', safe_y
    )
    if preferred_zone == 'top':
        preferred_top = (
            _style_number(romanization_style, 'marginv', safe_y)
            if rom_extent and romanization_style else trans_preferred_margin
        )
    else:
        preferred_top = (
            play_res_y - trans_preferred_margin - trans_extent.height
            - (rom_extent.height + padding if rom_extent else 0)
        )
    preferred_top = max(lowest_top, min(highest_top, preferred_top))

    candidates = []
    for top in tops:
        if rom_extent:
            rom_box = _centered_box(top, rom_extent, play_res_x, safe_x)
            trans_top = rom_box.bottom + padding
        else:
            rom_box = None
            trans_top = top
        trans_box = _centered_box(trans_top, trans_extent, play_res_x, safe_x)
        overlap = sum(
            trans_box.intersection_area(obstacle)
            + (rom_box.intersection_area(obstacle) if rom_box else 0)
            for obstacle in obstacles
        )
        distance = abs(top - preferred_top)
        candidates.append((overlap, distance, top, trans_box, rom_box))
    _, _, _, trans_box, rom_box = min(candidates, key=lambda item: item[:3])

    alignment = 8 if preferred_zone == "top" else 2
    if alignment == 8:
        trans_margin = round(trans_box.top)
        rom_margin = round(rom_box.top) if rom_box else None
    else:
        trans_margin = round(play_res_y - trans_box.bottom)
        rom_margin = round(play_res_y - rom_box.bottom) if rom_box else None

    return LayoutPlan(
        zone=preferred_zone,
        alignment=alignment,
        transcription_marginv=max(0, trans_margin),
        romanization_marginv=max(0, rom_margin) if rom_margin is not None else None,
        transcription_fontsize=trans_font,
        romanization_fontsize=rom_font,
        transcription_box=trans_box,
        romanization_box=rom_box,
    )
