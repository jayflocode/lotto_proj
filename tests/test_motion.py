import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from entropy.data import connect, ny_rows, store
from entropy.motion import DEFAULT_EVIDENCE, analyze_motion, validate_evidence
from entropy.motion_view import render_motion


class MotionTests(unittest.TestCase):
    def setUp(self):
        self.db = connect(":memory:")
        self.addCleanup(self.db.close)
        self.evidence = json.loads(DEFAULT_EVIDENCE.read_text())
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "evidence.json"
        self.end = date(2026, 11, 23)

    def seed_official(self, *clips):
        rows = [{"draw_date": clip["date"], "multiplier": "2",
                 "winning_numbers": " ".join(map(str, [*clip["white_in_order"], 1]))}
                for clip in clips]
        store(self.db, "https://example.test/draw", json.dumps(rows).encode(), ny_rows,
              date(2026, 11, 11), self.end)

    def run_report(self, end=None):
        self.path.write_text(json.dumps(self.evidence))
        return analyze_motion(self.db, end or self.end, self.path)

    def test_verified_cohort_and_sensitivity(self):
        self.seed_official(*self.evidence["clips"])
        result = self.run_report()
        self.assertEqual(result["coverage"]["verified_draws"], 6)
        self.assertEqual(result["coverage"]["missing_footage_dates"], [])
        self.assertEqual([row["fifth_lower_both_methods"] for row in result["phase_comparison"]],
                         [6, 6, 6])
        self.assertIn("6 of 6 eligible draws", render_motion(result))

    def test_excludes_unmatched_results_and_reports_missing_clip(self):
        first, second, *_ = self.evidence["clips"]
        self.seed_official(first, {**second, "white_in_order": [1, 2, 3, 4, 5]})
        del self.evidence["clips"][2]
        result = self.run_report(date(2026, 11, 18))
        self.assertEqual(result["coverage"]["missing_footage_dates"], ["2026-11-16"])
        self.assertEqual([row["reason"] for row in result["coverage"]["excluded"]],
                         ["white_ball_mismatch", "missing_official_draw"])
        self.assertEqual([row["date"] for row in result["draws"]], [first["date"]])

    def test_low_coverage_stays_missing(self):
        first = self.evidence["clips"][0]
        self.seed_official(first)
        first["measurements"]["nominal"][4]["farneback"] = {
            "usable_pairs": 2, "chamber_widths_per_s": None,
        }
        nominal = self.run_report()["phase_comparison"][1]
        self.assertEqual(nominal["eligible_draws"], 0)
        self.assertEqual(nominal["ineligible_dates"], [first["date"]])
        self.assertIsNone(nominal["median_fifth_minus_second"]["dis"])

    def test_refuses_duplicate_video_bytes_and_impossible_measurement(self):
        first, second, *_ = self.evidence["clips"]
        digest = first["sha256"]
        first["sha256"] = second["sha256"]
        with self.assertRaisesRegex(ValueError, "duplicate footage"):
            validate_evidence(self.evidence)
        first["sha256"] = digest
        first["measurements"]["early"][0]["dis"]["chamber_widths_per_s"] = float("nan")
        with self.assertRaisesRegex(ValueError, "invalid dis reading"):
            validate_evidence(self.evidence)
