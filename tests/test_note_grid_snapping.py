import gzip
import io
import json
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from src.engines import ENGINE_PROFILES, default_engine_path
from src.nextrush_leveldata import usc_to_leveldata
from src.osu_parser import HitObject, OsuChart, TimingPoint
from src.osu_to_usc import (
    NOTE_SNAP_DIVISIONS,
    beat_to_time_ms,
    build_bpm_segments,
    note_time_ms_to_beat,
    osu_to_usc,
    time_ms_to_beat,
)
from src.scp_writer import build_scp
from tests.helpers import make_osz


def tap(time, x=42):
    return HitObject(x=x, y=192, time=time, type=1, hit_sound=0)


def hold(time, end_time, x=42):
    return HitObject(x=x, y=192, time=time, type=128, hit_sound=0, end_time=end_time)


def chart_with(notes, timing_points=None):
    return OsuChart(
        mode=3,
        circle_size=6,
        timing_points=timing_points or [TimingPoint(time=1000, beat_length=500)],
        hit_objects=notes,
    )


def fields(entity):
    return {entry["name"]: entry.get("value", entry.get("ref")) for entry in entity["data"]}


class NoteGridSnappingTests(unittest.TestCase):
    def test_one_ms_limit_is_inclusive_in_both_directions(self):
        segments = build_bpm_segments([TimingPoint(time=1000, beat_length=500)])
        for time in (1749, 1750, 1751):
            with self.subTest(time=time):
                self.assertEqual(note_time_ms_to_beat(time, segments), 1.5)
        for time in (1748.99999, 1751.00001):
            with self.subTest(time=time):
                self.assertEqual(note_time_ms_to_beat(time, segments), time_ms_to_beat(time, segments))

    def test_common_binary_and_triplet_subdivisions(self):
        segments = build_bpm_segments([TimingPoint(time=1000, beat_length=480)])
        for division in NOTE_SNAP_DIVISIONS:
            target = 5 + 1 / division
            for error in (-0.75, 0.75):
                with self.subTest(division=division, error=error):
                    source_time = beat_to_time_ms(target, segments) + error
                    self.assertAlmostEqual(note_time_ms_to_beat(source_time, segments), target)

    def test_genuine_fine_grid_and_off_grid_notes_stay_unchanged(self):
        segments = build_bpm_segments([TimingPoint(time=0, beat_length=500)])
        for target in (10.4375, 2 + 1 / 24, 1.49):
            with self.subTest(beat=target):
                source_time = beat_to_time_ms(target, segments)
                self.assertEqual(note_time_ms_to_beat(source_time, segments), time_ms_to_beat(source_time, segments))

    def test_distance_uses_both_sides_of_a_bpm_change(self):
        segments = build_bpm_segments([
            TimingPoint(time=0, beat_length=500),
            TimingPoint(time=999.8, beat_length=1000),
        ])
        self.assertAlmostEqual(beat_to_time_ms(2, segments), 1000.2)
        self.assertEqual(note_time_ms_to_beat(999, segments), time_ms_to_beat(999, segments))
        self.assertEqual(note_time_ms_to_beat(1000, segments), 2)
        for time in (0, 999, 999.8, 1000, 1500):
            with self.subTest(time=time):
                self.assertAlmostEqual(beat_to_time_ms(time_ms_to_beat(time, segments), segments), time)

    def test_nearest_grid_is_measured_in_time_not_beat_distance(self):
        segments = build_bpm_segments([
            TimingPoint(time=0, beat_length=500),
            TimingPoint(time=984.25, beat_length=5),
        ])
        # 1.9375 is closer in beats, but 2.0 is closer in audio time across the tempo change.
        self.assertEqual(note_time_ms_to_beat(984, segments), 2)
        self.assertLess(abs(beat_to_time_ms(2, segments) - 984), 1)

    def test_nonnegative_clamp_and_default_timing_are_preserved(self):
        segments = build_bpm_segments([TimingPoint(time=1000, beat_length=500)])
        self.assertEqual(note_time_ms_to_beat(900, segments), 0)
        self.assertEqual(note_time_ms_to_beat(999, segments), 0)
        self.assertEqual(note_time_ms_to_beat(749, []), 1.5)

    def test_taps_heads_tails_snap_but_timing_and_offset_do_not(self):
        chart = chart_with([tap(1500), hold(1750, 2500)], [
            TimingPoint(time=1000.25, beat_length=500),
            TimingPoint(time=1999.7, beat_length=-50, uninherited=0),
            TimingPoint(time=3000.4, beat_length=250),
        ])
        usc = osu_to_usc(chart)
        notes = [o for o in usc["objects"] if o["type"] in ("single", "slide")]
        self.assertEqual(notes[0]["beat"], 1)
        self.assertEqual([c["beat"] for c in notes[1]["connections"]], [1.5, 3])
        self.assertEqual(usc["offset"], 1.00025)
        segments = build_bpm_segments(chart.red_timing_points)
        bpms = [o for o in usc["objects"] if o["type"] == "bpm"]
        self.assertEqual(bpms[1]["beat"], time_ms_to_beat(3000.4, segments))
        group = next(o for o in usc["objects"] if o["type"] == "timeScaleGroup")
        self.assertEqual(group["changes"][1]["beat"], time_ms_to_beat(1999.7, segments))
        self.assertEqual([o.time for o in chart.hit_objects], [1500, 1750])
        self.assertEqual(chart.hit_objects[1].end_time, 2500)

    def test_chords_remain_simultaneous(self):
        usc = osu_to_usc(chart_with([tap(1749), tap(1749, x=469), hold(1749, 2499, x=256)]))
        notes = [o for o in usc["objects"] if o["type"] in ("single", "slide")]
        beats = [o["beat"] if o["type"] == "single" else o["connections"][0]["beat"] for o in notes]
        self.assertEqual(beats, [1.5, 1.5, 1.5])

    def test_colliding_snaps_are_reverted_for_all_simultaneous_notes(self):
        usc = osu_to_usc(chart_with([tap(1749), tap(1749, x=469), tap(1751)]))
        beats = [o["beat"] for o in usc["objects"] if o["type"] == "single"]
        self.assertEqual(beats, [1.498, 1.498, 1.502])

    def test_short_hold_does_not_collapse_or_cross_neighbor(self):
        usc = osu_to_usc(chart_with([hold(1749, 1751), tap(1750, x=469)]))
        slide = next(o for o in usc["objects"] if o["type"] == "slide")
        self.assertEqual([c["beat"] for c in slide["connections"]], [1.498, 1.502])
        single = next(o for o in usc["objects"] if o["type"] == "single")
        self.assertEqual(single["beat"], 1.5)

    def test_restoring_a_conflict_also_checks_its_neighbors(self):
        chart = chart_with([tap(1500), tap(1501), tap(1502)])
        candidates = {1500: 1.002, 1501: 1.004, 1502: 1.004}
        with patch("src.osu_to_usc.note_time_ms_to_beat", side_effect=lambda t, _: candidates[t]):
            usc = osu_to_usc(chart)
        beats = [o["beat"] for o in usc["objects"] if o["type"] == "single"]
        self.assertEqual(beats, [1, 1.002, 1.004])

    def test_quantized_head_no_longer_generates_an_extra_tick(self):
        chart = chart_with([hold(1821, 2487)], [
            TimingPoint(time=1321.10743580023, beat_length=333.333333333333),
        ])
        usc = osu_to_usc(chart)
        slide = next(o for o in usc["objects"] if o["type"] == "slide")
        self.assertEqual([c["beat"] for c in slide["connections"]], [1.5, 3.5])
        data = usc_to_leveldata(usc)
        ticks = [fields(e)["#BEAT"] for e in data["entities"] if e["archetype"] == "TransientHiddenTickNote"]
        self.assertEqual(ticks, [2, 2.5, 3])

    def test_native_usc_is_not_resnapped_and_close_ticks_are_not_filtered(self):
        usc = {
            "objects": [
                {"type": "bpm", "beat": 0, "bpm": 180},
                {"type": "slide", "connections": [
                    {"type": "start", "beat": 10.4375, "lane": 0, "size": 2, "judgeType": "normal"},
                    {"type": "end", "beat": 14.4375, "lane": 0, "size": 2, "judgeType": "normal"},
                ]},
            ],
        }
        data = usc_to_leveldata(usc)
        ticks = [fields(e)["#BEAT"] for e in data["entities"] if e["archetype"] == "TransientHiddenTickNote"]
        self.assertEqual(ticks, [10.5, 11, 11.5, 12, 12.5, 13, 13.5, 14])

    def test_both_engine_packages_use_the_same_snapped_leveldata(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            base = make_osz(directory / "base.osz", keys=(6,))
            source = directory / "snapping.osz"
            with zipfile.ZipFile(base) as original, zipfile.ZipFile(source, "w") as edited:
                for name in original.namelist():
                    content = original.read(name)
                    if name.endswith(".osu"):
                        content = content.replace(b",1745,128,", b",1749,128,")
                    edited.writestr(name, content)
            results = []
            for target in ENGINE_PROFILES:
                with self.subTest(target=target), redirect_stdout(io.StringIO()):
                    output = directory / f"{target}.scp"
                    self.assertEqual(build_scp(str(source), str(default_engine_path(target)), str(output),
                                               target_engine=target, background_mode="original"), 0)
                    with zipfile.ZipFile(output) as archive:
                        level = json.loads(archive.read("sonolus/levels/list"))["items"][0]
                        self.assertFalse(level["useBackground"]["useDefault"])
                        data = json.loads(gzip.decompress(archive.read(level["data"]["url"].lstrip("/"))))
                        results.append(data)
                        heads = [fields(e)["#BEAT"] for e in data["entities"] if e["archetype"].endswith("HeadTapNote")]
                        ticks = [fields(e)["#BEAT"] for e in data["entities"] if e["archetype"] == "TransientHiddenTickNote"]
                        self.assertEqual(heads, [1.5, 1.5])
                        self.assertEqual(sorted(ticks), [2, 2, 2.5, 2.5])
            self.assertEqual(results[0], results[1])


if __name__ == "__main__":
    unittest.main()
