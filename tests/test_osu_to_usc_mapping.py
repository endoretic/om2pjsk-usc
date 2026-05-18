import unittest

from src.osu_to_usc import mania_column_to_usc_lane_size


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


if __name__ == "__main__":
    unittest.main()
