import unittest

from src.osu_parser import HitObject, OsuChart, TimingPoint
from src.osu_to_usc import (
    is_tinged_column,
    mania_column_to_usc_lane_size,
    osu_to_usc,
)


class OsuToUscMappingTest(unittest.TestCase):
    def test_key4_lane_size_matches_reference(self) -> None:
        self.assertEqual(
            [mania_column_to_usc_lane_size(4, col) for col in range(4)],
            [(-4.5, 1.5), (-1.5, 1.5), (1.5, 1.5), (4.5, 1.5)],
        )

    def test_key5_lane_size_matches_reference(self) -> None:
        expected = [(-4.8, 1.2), (-2.4, 1.2), (0.0, 1.2), (2.4, 1.2), (4.8, 1.2)]
        actual = [mania_column_to_usc_lane_size(5, col) for col in range(5)]
        for (lane, size), (expected_lane, expected_size) in zip(actual, expected):
            self.assertAlmostEqual(lane, expected_lane)
            self.assertAlmostEqual(size, expected_size)

    def test_key6_lane_size_matches_reference(self) -> None:
        self.assertEqual(
            [mania_column_to_usc_lane_size(6, col) for col in range(6)],
            [(-5.0, 1.0), (-3.0, 1.0), (-1.0, 1.0), (1.0, 1.0), (3.0, 1.0), (5.0, 1.0)],
        )

    def test_tinged_columns_match_reference_tracks(self) -> None:
        self.assertEqual(
            [is_tinged_column(4, col) for col in range(4)],
            [True, False, False, True],
        )
        self.assertEqual(
            [is_tinged_column(5, col) for col in range(5)],
            [False, True, False, True, False],
        )
        self.assertEqual(
            [is_tinged_column(6, col) for col in range(6)],
            [False, True, False, False, True, False],
        )

    def test_tinged_columns_mark_taps_and_holds_critical(self) -> None:
        chart = OsuChart(
            mode=3,
            circle_size=6,
            timing_points=[TimingPoint(time=0, beat_length=500)],
            hit_objects=[
                _tap(6, 0, 1000),
                _tap(6, 1, 1100),
                _hold(6, 2, 1200, 1400),
                _tap(6, 3, 1300),
                _hold(6, 4, 1400, 1600),
                _tap(6, 5, 1500),
            ],
        )

        usc = osu_to_usc(chart, tinged_columns=True)
        notes = [obj for obj in usc["objects"] if obj["type"] in {"single", "slide"}]

        self.assertEqual(
            [note["critical"] for note in notes],
            [False, True, False, False, True, False],
        )


def _column_center_x(key_count: int, col: int) -> int:
    return int((col + 0.5) * 512 / key_count)


def _tap(key_count: int, col: int, time: int) -> HitObject:
    return HitObject(
        x=_column_center_x(key_count, col),
        y=192,
        time=time,
        type=1,
        hit_sound=0,
    )


def _hold(key_count: int, col: int, time: int, end_time: int) -> HitObject:
    return HitObject(
        x=_column_center_x(key_count, col),
        y=192,
        time=time,
        type=128,
        hit_sound=0,
        end_time=end_time,
    )


if __name__ == "__main__":
    unittest.main()
