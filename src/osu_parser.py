"""osu!mania .osu file parser.

Parses .osu file sections: General, Metadata, Difficulty, Events,
TimingPoints, HitObjects.  Only accepts Mode: 3 (mania).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from math import floor
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class TimingPoint:
    """A single timing point (red or green line)."""
    time: float  # ms, decimal allowed
    beat_length: float  # ms/beat (positive=red, negative=green)
    meter: int = 4
    sample_set: int = 0
    sample_index: int = 0
    volume: int = 100
    uninherited: int = 1  # 1=red, 0=green
    effects: int = 0

    @property
    def is_red(self) -> bool:
        return self.uninherited == 1

    @property
    def bpm(self) -> float:
        """BPM for red lines. Returns 0 for green lines."""
        if self.is_red and self.beat_length > 0:
            return 60000.0 / self.beat_length
        return 0.0

    @property
    def sv_multiplier(self) -> float:
        """SV multiplier for green lines. Returns 1.0 for red lines."""
        if not self.is_red and self.beat_length != 0:
            return 100.0 / abs(self.beat_length)
        return 1.0


@dataclass
class HitObject:
    """A single hit object (tap or hold)."""
    x: int
    y: int
    time: int  # ms
    type: int  # bit flags
    hit_sound: int
    end_time: Optional[int] = None  # hold end time (ms)
    hit_sample: str = "0:0:0:0:"

    @property
    def is_hold(self) -> bool:
        return (self.type & 128) != 0

    @property
    def is_tap(self) -> bool:
        return (self.type & 1) != 0

    def lane(self, key_count: int) -> int:
        """0-based column index. MUST use floor(), NEVER round()."""
        col = floor(self.x * key_count / 512)
        return max(0, min(key_count - 1, col))

    @property
    def duration(self) -> int:
        """Hold duration in ms. 0 for taps."""
        if self.end_time is not None and self.is_hold:
            return self.end_time - self.time
        return 0


@dataclass
class OsuChart:
    """Parsed osu!mania chart."""
    audio_filename: str = ""
    audio_lead_in: int = 0
    preview_time: int = -1
    mode: int = 0
    title: str = ""
    artist: str = ""
    creator: str = ""
    version: str = ""
    beatmap_id: int = 0
    beatmap_set_id: int = 0
    hp: float = 0.0
    circle_size: float = 0.0
    overall_difficulty: float = 0.0
    approach_rate: float = 0.0
    background_filename: str = ""
    timing_points: List[TimingPoint] = field(default_factory=list)
    hit_objects: List[HitObject] = field(default_factory=list)

    @property
    def key_count(self) -> int:
        return int(floor(self.circle_size))

    @property
    def is_mania(self) -> bool:
        return self.mode == 3

    @property
    def is_placeholder(self) -> bool:
        """Detect placeholder/empty charts (1 or fewer hit objects)."""
        return len(self.hit_objects) <= 1

    @property
    def red_timing_points(self) -> List[TimingPoint]:
        return [tp for tp in self.timing_points if tp.is_red]

    @property
    def green_timing_points(self) -> List[TimingPoint]:
        return [tp for tp in self.timing_points if not tp.is_red]

    @property
    def first_red_time(self) -> Optional[float]:
        reds = self.red_timing_points
        return reds[0].time if reds else None


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_SECTION_RE = re.compile(r"^\[([^\]]+)\]$")
_KV_RE = re.compile(r"^([A-Za-z0-9]+)\s*:\s*(.*)$")
_HITOBJECT_RE = re.compile(
    r"^(\d+),(\d+),(\d+),(\d+),(\d+),([^,]*)$"
)


def parse_osu(text: str) -> OsuChart:
    """Parse .osu file text into an OsuChart."""
    chart = OsuChart()
    current_section: Optional[str] = None
    lines = text.splitlines()

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue

        # Section header
        m = _SECTION_RE.match(line)
        if m:
            current_section = m.group(1).strip()
            continue

        if current_section is None:
            continue

        if current_section == "HitObjects":
            _parse_hitobject(chart, line)
        elif current_section == "TimingPoints":
            _parse_timingpoint(chart, line)
        elif current_section == "Events":
            _parse_event(chart, line)
        else:
            m = _KV_RE.match(line)
            if m:
                key = m.group(1).strip()
                value = m.group(2).strip()
                _apply_kv(chart, current_section, key, value)

    return chart


# ---------------------------------------------------------------------------
# Section-specific parsers
# ---------------------------------------------------------------------------

def _parse_timingpoint(chart: OsuChart, line: str) -> None:
    parts = line.split(",")
    if len(parts) < 7:
        return
    try:
        tp = TimingPoint(
            time=float(parts[0]),
            beat_length=float(parts[1]),
            meter=int(parts[2]) if parts[2] else 4,
            sample_set=int(parts[3]) if parts[3] else 0,
            sample_index=int(parts[4]) if parts[4] else 0,
            volume=int(parts[5]) if parts[5] else 100,
            uninherited=int(parts[6]) if parts[6] else 1,
            effects=int(parts[7]) if len(parts) > 7 and parts[7] else 0,
        )
        chart.timing_points.append(tp)
    except (ValueError, IndexError):
        pass


def _parse_hitobject(chart: OsuChart, line: str) -> None:
    """Parse a HitObject line.

    Format: x,y,time,type,hitSound,objectParams,hitSample
    For holds: objectParams = endTime:hitSample
    For taps:   objectParams = 0:0:0:0:
    """
    parts = line.split(",")
    if len(parts) < 6:
        return
    try:
        x = int(parts[0])
        y = int(parts[1])
        time = int(parts[2])
        obj_type = int(parts[3])
        hit_sound = int(parts[4])

        end_time: Optional[int] = None
        hit_sample = "0:0:0:0:"

        if len(parts) >= 6:
            # The remainder after the 5th comma may contain endTime for holds
            remainder = ",".join(parts[5:])
            # Check if this is a hold: type & 128 != 0
            if obj_type & 128:
                # Hold format: endTime:hitSample,extrastuff
                # e.g.: "1966:0:0:0:0:"
                colon_idx = remainder.find(":")
                if colon_idx > 0:
                    try:
                        end_time = int(remainder[:colon_idx])
                    except ValueError:
                        pass
                    hit_sample = remainder[colon_idx + 1:]
            else:
                # Tap format: 0:0:0:0:
                hit_sample = remainder

        chart.hit_objects.append(HitObject(
            x=x, y=y, time=time, type=obj_type,
            hit_sound=hit_sound, end_time=end_time,
            hit_sample=hit_sample,
        ))
    except (ValueError, IndexError):
        pass


def _parse_event(chart: OsuChart, line: str) -> None:
    """Parse Events section for background image."""
    # Background format: 0,0,"filename",0,0
    if line.startswith("0,0,"):
        # Extract filename between quotes
        m = re.search(r'"([^"]*)"', line)
        if m:
            chart.background_filename = m.group(1)


def _apply_kv(chart: OsuChart, section: str, key: str, value: str) -> None:
    """Apply a key-value pair to the chart based on section."""
    key_lower = key.lower()

    if section == "General":
        if key_lower == "audiofilename":
            chart.audio_filename = value
        elif key_lower == "audioleadin":
            chart.audio_lead_in = int(value) if value else 0
        elif key_lower == "previewtime":
            chart.preview_time = int(value) if value else -1
        elif key_lower == "mode":
            chart.mode = int(value) if value else 0

    elif section == "Metadata":
        if key_lower == "title":
            chart.title = value
        elif key_lower == "artist":
            chart.artist = value
        elif key_lower == "creator":
            chart.creator = value
        elif key_lower == "version":
            chart.version = value
        elif key_lower == "beatmapid":
            chart.beatmap_id = int(value) if value else 0
        elif key_lower == "beatmapsetid":
            chart.beatmap_set_id = int(value) if value else 0

    elif section == "Difficulty":
        if key_lower == "circlesize":
            chart.circle_size = float(value) if value else 0.0
        elif key_lower == "hpdrainrate":
            chart.hp = float(value) if value else 0.0
        elif key_lower == "overalldifficulty":
            chart.overall_difficulty = float(value) if value else 0.0
        elif key_lower == "approachrate":
            chart.approach_rate = float(value) if value else 0.0
