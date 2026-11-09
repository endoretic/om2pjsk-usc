import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from osu_mania_to_scp import filter_valid_charts, main, parse_all_charts, read_osz
from src.osu_parser import HitObject, OsuChart, TimingPoint
from src.osu_to_usc import mania_column_to_usc_lane_size, osu_to_usc
from tests.helpers import make_osz


class SevenKeyTests(unittest.TestCase):
    def test_column_boundaries_use_floor_including_right_edge(self):
        boundaries = (74, 147, 220, 293, 366, 439)
        for x in range(513):
            with self.subTest(x=x):
                note = HitObject(x=x, y=192, time=1000, type=1, hit_sound=0)
                self.assertEqual(note.lane(7), sum(x >= boundary for boundary in boundaries))

    def test_seven_columns_cover_the_stage_symmetrically(self):
        previous_right = -6
        for col in range(7):
            lane, size = mania_column_to_usc_lane_size(7, col)
            self.assertAlmostEqual(lane, 12 * (col - 3) / 7)
            self.assertAlmostEqual(size, 6 / 7)
            self.assertAlmostEqual(lane - size, previous_right)
            self.assertAlmostEqual(lane, -mania_column_to_usc_lane_size(7, 6 - col)[0])
            previous_right = lane + size
        self.assertAlmostEqual(previous_right, 6)
        self.assertEqual(mania_column_to_usc_lane_size(7, 3)[0], 0)

    def test_taps_and_holds_in_all_columns_keep_snapping_and_tail_modes(self):
        positions = (36, 109, 182, 256, 329, 402, 475)
        chart = OsuChart(
            mode=3, circle_size=7,
            timing_points=[TimingPoint(time=1000, beat_length=500)],
            hit_objects=[HitObject(x=x, y=192, time=1749, type=1, hit_sound=0) for x in positions]
            + [HitObject(x=x, y=192, time=1999, type=128, hit_sound=0, end_time=3499) for x in positions],
        )
        for tail_mode, judge_type in (("release", "normal"), ("trace", "trace"), ("none", "none")):
            for tinged in (False, True):
                with self.subTest(tail=tail_mode, tinged=tinged):
                    usc = osu_to_usc(chart, tail_mode=tail_mode, tinged_columns=tinged)
                    self.assertEqual(usc["offset"], 1)
                    taps = [o for o in usc["objects"] if o["type"] == "single"]
                    slides = [o for o in usc["objects"] if o["type"] == "slide"]
                    self.assertEqual(len(taps), 7)
                    self.assertEqual(len(slides), 7)
                    for col, (tap, slide) in enumerate(zip(taps, slides)):
                        critical = tinged and col in (1, 3, 5)
                        head, tail = slide["connections"]
                        for note in (tap, head, tail):
                            self.assertAlmostEqual(note["lane"], 12 * (col - 3) / 7)
                            self.assertAlmostEqual(note["size"], 6 / 7)
                            self.assertEqual(note["critical"], critical)
                        self.assertEqual(slide["critical"], critical)
                        self.assertEqual(tap["beat"], 1.5)
                        self.assertEqual((head["beat"], tail["beat"]), (2, 5))
                        self.assertEqual(head["judgeType"], "normal")
                        self.assertEqual(tail["judgeType"], judge_type)

    def test_parser_and_cli_accept_seven_keys_without_extra_options(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = make_osz(directory / "seven.osz", keys=(7,), all_columns=True)
            charts = filter_valid_charts(parse_all_charts(read_osz(str(source))))
            self.assertEqual(len(charts), 1)
            self.assertEqual(charts[0].key_count, 7)
            self.assertEqual({note.lane(7) for note in charts[0].hit_objects}, set(range(7)))
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main([str(source), "--list"]), 0)
                self.assertIn("[7K]", output.getvalue())
            with redirect_stdout(io.StringIO()):
                self.assertEqual(main([str(source), "--dump-usc", str(directory / "usc")]), 0)
            usc = json.loads((directory / "usc" / "7K.usc.json").read_text(encoding="utf-8"))
            self.assertEqual(sum(o["type"] == "single" for o in usc["objects"]), 8)
            self.assertEqual(sum(o["type"] == "slide" for o in usc["objects"]), 7)


if __name__ == "__main__":
    unittest.main()
