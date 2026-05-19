"""osu!mania chart → USC (Universal Sonolus Chart) JSON converter.

Converts parsed osu!mania charts into the USC format expected by
NextRUSH+.  Handles timing model (BPM segments, beat conversion),
lane/size mapping, and object conversion (tap→single, hold→slide).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List

from .osu_parser import OsuChart, TimingPoint

# Stage width for NextRUSH+ lane mapping
STAGE_WIDTH = 12.0

TAIL_MODES = {
    "release",
    "trace",
}

TINGED_COLUMNS_BY_KEY = {
    4: {0, 3},
    5: {1, 3},
    6: {1, 4},
}


def mania_column_to_usc_lane_size(key_count: int, col: int) -> tuple[float, float]:
    """Map a 0-based mania column to USC lane center and note half-size."""
    column_width = STAGE_WIDTH / key_count
    lane = -STAGE_WIDTH / 2 + (col + 0.5) * column_width
    size = column_width / 2
    return lane, size


def is_tinged_column(key_count: int, col: int) -> bool:
    """Return whether a 0-based mania column is part of Tinged Columns."""
    return col in TINGED_COLUMNS_BY_KEY.get(key_count, set())


# ---------------------------------------------------------------------------
# Timing model
# ---------------------------------------------------------------------------

@dataclass
class BpmSegment:
    start_ms: float
    beat_at_start: float
    beat_length_ms: float  # ms per beat
    bpm: float


def build_bpm_segments(red_timing_points: List[TimingPoint]) -> List[BpmSegment]:
    """Build BPM segments from sorted red timing points.

    The first red timing point is beat 0.  Subsequent red points define
    new BPM segments starting at their time.
    """
    if not red_timing_points:
        # Default: 120 BPM at time 0
        return [BpmSegment(start_ms=0.0, beat_at_start=0.0, beat_length_ms=500.0, bpm=120.0)]

    sorted_reds = sorted(red_timing_points, key=lambda tp: tp.time)
    segments: List[BpmSegment] = []

    for i, tp in enumerate(sorted_reds):
        if i == 0:
            beat_at_start = 0.0
        else:
            prev = segments[-1]
            beat_at_start = prev.beat_at_start + (tp.time - prev.start_ms) / prev.beat_length_ms

        beat_length = tp.beat_length
        bpm = tp.bpm
        segments.append(BpmSegment(
            start_ms=tp.time,
            beat_at_start=beat_at_start,
            beat_length_ms=beat_length,
            bpm=bpm,
        ))

    return segments


def time_ms_to_beat(time_ms: float, segments: List[BpmSegment]) -> float:
    """Convert milliseconds to beats using BPM segments."""
    if not segments:
        return time_ms / 500.0  # default 120 BPM

    # Find the segment that contains this time
    seg = segments[0]
    for s in segments:
        if s.start_ms <= time_ms + 1e-6:
            seg = s
        else:
            break

    return seg.beat_at_start + (time_ms - seg.start_ms) / seg.beat_length_ms


# ---------------------------------------------------------------------------
# USC builder
# ---------------------------------------------------------------------------

def _tail_connection_fields(tail_mode: str) -> Dict[str, str]:
    """Return USC fields for a hold tail style."""
    if tail_mode not in TAIL_MODES:
        raise ValueError(f"Unsupported tail mode: {tail_mode}")
    if tail_mode == "trace":
        return {"judgeType": "trace"}
    return {"judgeType": "normal"}


class USCBuilder:
    """Builds a USC JSON structure from parsed chart data."""

    def __init__(
        self,
        chart: OsuChart,
        tail_mode: str = "release",
        tinged_columns: bool = False,
    ):
        if tail_mode not in TAIL_MODES:
            raise ValueError(f"Unsupported tail mode: {tail_mode}")
        self.chart = chart
        self.tail_mode = tail_mode
        self.tinged_columns = tinged_columns
        self.bpm_segments = build_bpm_segments(chart.red_timing_points)
        self._objects: List[Dict[str, Any]] = []

    def add_bpm_objects(self) -> None:
        """Add BPM change objects."""
        for seg in self.bpm_segments:
            self._objects.append({
                "type": "bpm",
                "beat": seg.beat_at_start,
                "bpm": seg.bpm,
            })

    def add_time_scale_group(self) -> None:
        """Add timeScaleGroup with changes from green timing points."""
        greens = sorted(self.chart.green_timing_points, key=lambda tp: tp.time)
        changes: List[Dict[str, Any]] = []

        # Always include a base timeScale=1 at beat 0
        changes.append({"beat": 0.0, "timeScale": 1.0})

        for g in greens:
            beat = time_ms_to_beat(g.time, self.bpm_segments)
            # Only add if it differs from the last
            if abs(beat - changes[-1]["beat"]) < 1e-6:
                changes[-1]["timeScale"] = g.sv_multiplier
            else:
                changes.append({"beat": beat, "timeScale": g.sv_multiplier})

        self._objects.append({
            "type": "timeScaleGroup",
            "changes": changes,
        })

    def add_notes(self) -> None:
        """Convert HitObjects to USC single/slide objects."""
        key_count = self.chart.key_count

        for ho in self.chart.hit_objects:
            col = ho.lane(key_count)
            lane, size = mania_column_to_usc_lane_size(key_count, col)
            beat = time_ms_to_beat(ho.time, self.bpm_segments)
            critical = self.tinged_columns and is_tinged_column(key_count, col)

            if not ho.is_hold:
                # Tap → single
                self._objects.append({
                    "type": "single",
                    "beat": beat,
                    "lane": lane,
                    "size": size,
                    "critical": critical,
                    "trace": False,
                    "timeScaleGroup": 0,
                })
            else:
                # Hold → slide
                end_beat = time_ms_to_beat(ho.end_time, self.bpm_segments)
                tail_connection = {
                    "type": "end",
                    "beat": end_beat,
                    "lane": lane,
                    "size": size,
                    "critical": critical,
                    "timeScaleGroup": 0,
                }
                tail_connection.update(_tail_connection_fields(self.tail_mode))
                self._objects.append({
                    "type": "slide",
                    "critical": critical,
                    "connections": [
                        {
                            "type": "start",
                            "beat": beat,
                            "lane": lane,
                            "size": size,
                            "critical": critical,
                            "ease": "linear",
                            "judgeType": "normal",
                            "timeScaleGroup": 0,
                        },
                        tail_connection,
                    ],
                })

    def build(self) -> Dict[str, Any]:
        """Build and return the full USC dictionary."""
        # First red timing point is beat 0 in USC; offset places that beat
        # back on the source osu! audio timeline.
        first_red = self.chart.first_red_time
        if first_red is not None:
            offset = first_red / 1000.0
        else:
            offset = 0.0

        self._objects = []
        self.add_bpm_objects()
        self.add_time_scale_group()
        self.add_notes()

        return {
            "offset": offset,
            "objects": self._objects,
        }


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------

def osu_to_usc(
    chart: OsuChart,
    tail_mode: str = "release",
    tinged_columns: bool = False,
) -> Dict[str, Any]:
    """Convert a parsed osu!mania chart to USC JSON."""
    builder = USCBuilder(
        chart,
        tail_mode=tail_mode,
        tinged_columns=tinged_columns,
    )
    return builder.build()


def osu_to_usc_json(
    chart: OsuChart,
    indent: int = 2,
    tail_mode: str = "release",
    tinged_columns: bool = False,
) -> str:
    """Convert to USC JSON string."""
    usc = osu_to_usc(
        chart,
        tail_mode=tail_mode,
        tinged_columns=tinged_columns,
    )
    return json.dumps(usc, ensure_ascii=False, indent=indent)
