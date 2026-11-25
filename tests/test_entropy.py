import json
import sqlite3
import unittest
from datetime import date, datetime, timezone
from random import Random

from entropy.data import (
    ARCHIVE, DOUBLE_START, START, archive_rows, audit, connect, cutoff,
    draw_days, ny_rows, store, update, validated_draw,
)
from entropy.history import analyze_history, binomial_test
from entropy.prospective import analyze_prospective, load_protocol
from entropy.stats import analyze, uniform_draw


def state_row(day, balls="1 2 3 4 5 6", multiplier="2"):
    return {"draw_date": f"{day}T00:00:00", "winning_numbers": balls,
            "multiplier": multiplier}


def state_body(*rows):
    return json.dumps(rows).encode()


def card(game, day, whites=(1, 2, 3, 4, 5), red=6):
    white_class, red_class = (("white-balls", "powerball") if game == "powerball"
                              else ("black-balls", "dp-powerball"))
    balls = "".join(f'<div class="{white_class}"><div>{ball}</div></div>' for ball in whites)
    balls += f'<div class="{red_class}"><div>{red}</div></div>'
    multiplier = '<span class="multiplier">2x</span>' if game == "powerball" else ""
    return (f'<a class="card" href="/draw-result?gc={game}&amp;date={day}">'
            f'{balls}{multiplier}</a>').encode()


class DataTests(unittest.TestCase):
    def setUp(self):
        self.db = connect(":memory:")
        self.addCleanup(self.db.close)

    def test_schedule_and_eastern_cutoff(self):
        self.assertEqual(draw_days(date(2021, 8, 16), DOUBLE_START), {
            date(2021, 8, 18), date(2021, 8, 21), DOUBLE_START,
        })
        before = datetime(2026, 11, 24, 3, 58, tzinfo=timezone.utc)
        after = before.replace(minute=59)
        self.assertEqual(cutoff(before), date(2026, 11, 21))
        self.assertEqual(cutoff(after), date(2026, 11, 23))

    def test_ball_validation_and_separate_pools(self):
        self.assertEqual(validated_draw(START, ["69", "9", "1", "2", "3", "9"], 10).balls,
                         (1, 2, 3, 9, 69, 9))
        for balls in ("1 1 3 4 5 6", "0 2 3 4 5 6", "1 2 3 4 70 6",
                      "1 2 3 4 5 27", "1 2 3 4 5"):
            with self.subTest(balls=balls), self.assertRaises(ValueError):
                validated_draw(START, balls.split())

    def test_archives_parse_date_balls_and_multiplier(self):
        for game in ("powerball", "pb-double-play"):
            row, = archive_rows(card(game, DOUBLE_START), game)
            self.assertEqual(row[1:3], (str(DOUBLE_START), "1 2 3 4 5 6"))
            self.assertEqual(row[3], "2" if game == "powerball" else "")

    def test_audit_flags_missing_duplicate_invalid_and_conflict(self):
        end = date(2015, 10, 10)
        clean = state_row(START)
        raw = state_body(clean, clean, state_row(end, "1 1 3 4 5 6"),
                         state_row(end, multiplier=None), state_row(START, "1 2 3 4 5 7"))
        for _ in range(2):
            store(self.db, "https://example.test/state", raw, ny_rows, START, end)
        report = audit(self.db, end)
        self.assertEqual(report["powerball"]["missing"], [str(end)])
        self.assertEqual(report["raw_responses"], 1)
        self.assertEqual({row["kind"] for row in report["source_issues"]},
                         {"duplicate_date", "invalid_row", "conflicting_result"})
        self.assertEqual(self.db.execute("SELECT body FROM raw_sources").fetchone()[0], raw)
        self.assertEqual(self.db.execute("SELECT red FROM powerball").fetchone()[0], 6)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE powerball SET red = 99")

    def test_audit_checks_preserved_source_bytes(self):
        store(self.db, "https://example.test/state", state_body(state_row(START)), ny_rows,
              START, START)
        self.assertEqual(audit(self.db, START)["raw_checksum_mismatches"], [])
        self.db.execute("UPDATE raw_sources SET body = ?", (b"changed",))
        self.assertEqual(audit(self.db, START)["raw_checksum_mismatches"],
                         [{"id": 1, "url": "https://example.test/state"}])

    def test_malformed_payload_is_preserved(self):
        store(self.db, "https://example.test/state", b"<html>", ny_rows, START, START)
        report = audit(self.db, START)
        self.assertEqual(report["source_issues"][0]["kind"], "parse_error")
        self.assertEqual(report["powerball"]["missing"], [str(START)])

    def test_incremental_update_adds_new_draw_and_is_idempotent(self):
        end = date(2015, 10, 10)
        available = [START]

        def download(url):
            if url.startswith(ARCHIVE):
                return b"".join(card("powerball", day) for day in available)
            return state_body(*(state_row(day) for day in available))

        self.assertEqual(update(self.db, START, download=download)["powerball"]["records"], 1)
        available.append(end)
        first = update(self.db, end, download=download)
        self.assertEqual(first, update(self.db, end, download=download))
        self.assertEqual(first["powerball"]["records"], 2)
        self.assertEqual(first["powerball"]["missing"], [])
        self.assertEqual(first["source_issues"], [])

    def test_analysis_is_seeded_and_keeps_samples_separate(self):
        oct_day, nov_day = date(2026, 10, 3), date(2026, 11, 2)
        raw = state_body(state_row(oct_day), state_row(nov_day, "2 4 6 8 10 12"))
        store(self.db, "https://example.test/state", raw, ny_rows, oct_day, nov_day)
        result = analyze(self.db, nov_day, trials=15, seed=42)
        self.assertEqual(result, analyze(self.db, nov_day, trials=15, seed=42))
        self.assertEqual(result["2026-10"]["mean_white_sum"], 15)
        self.assertEqual(result["2026-11"]["mean_powerball"], 12)
        self.assertTrue(result["2026-10"]["missing_draw_dates"])
        self.assertEqual(result["2026-11"]["missing_draw_dates"], [])
        self.assertEqual(result["holm_family_size"], 6)
        for pool, p_value in result["between_months_p"].items():
            self.assertGreaterEqual(result["holm_adjusted_p"]["between_months"][pool], p_value)
        for values in (result["between_months_p"], result["2026-10"]["uniform_p"]):
            self.assertTrue(all(1 / 16 <= value <= 1 for value in values.values()))

    def test_control_reproducibility_and_support(self):
        rng, same = Random(42), Random(42)
        for _ in range(1000):
            balls = uniform_draw(rng)
            self.assertEqual(balls, uniform_draw(same))
            self.assertEqual(tuple(sorted(set(balls[:5]))), balls[:5])
            self.assertTrue(all(1 <= ball <= 69 for ball in balls[:5]))
            self.assertTrue(1 <= balls[-1] <= 26)

    def test_history_compares_latest_draw_to_previous_counts(self):
        second = date(2015, 10, 10)
        raw = state_body(state_row(START), state_row(second, "1 2 7 8 9 6"))
        store(self.db, "https://example.test/state", raw, ny_rows, START, second)
        result = analyze_history(self.db, second)
        self.assertEqual(result["coverage"]["draws"], 2)
        self.assertEqual(result["latest_draw"]["white"][0],
                         {"number": 1, "previous_count": 1, "current_count": 2})
        self.assertEqual(result["latest_draw"]["consecutive_pair"], {
            "previous_date": str(START), "shared_white": [1, 2], "same_powerball": True,
        })
        repeat_tests = result["consecutive_draw_tests"]
        self.assertEqual(repeat_tests["pairs"], 1)
        self.assertEqual(repeat_tests["at_least_one_white"]["observed"], 1)
        self.assertEqual(repeat_tests["same_powerball"]["observed"], 1)
        self.assertEqual(result["holm_family_size"], 97)
        self.assertGreaterEqual(repeat_tests["same_powerball"]["holm_p_value"],
                                repeat_tests["same_powerball"]["p_value"])

    def test_history_skips_pairs_across_a_missing_draw(self):
        end = date(2015, 10, 14)
        raw = state_body(state_row(START), state_row(end))
        store(self.db, "https://example.test/state", raw, ny_rows, START, end)
        result = analyze_history(self.db, end)
        self.assertEqual(result["coverage"]["missing"], ["2015-10-10"])
        self.assertEqual(result["consecutive_draw_tests"], {"pairs": 0})
        self.assertIsNone(result["latest_draw"]["consecutive_pair"])

    def test_exact_binomial_probability_includes_ties_and_both_tails(self):
        self.assertAlmostEqual(binomial_test(0, 3, 0.5), 0.25)
        self.assertAlmostEqual(binomial_test(1, 3, 0.5), 1.0)
        self.assertAlmostEqual(binomial_test(1, 2, 0.25), 0.4375)

    def test_prospective_report_waits_for_the_registered_schedule(self):
        before = analyze_prospective(self.db, date(2026, 11, 21))
        self.assertEqual(before["status"], "waiting_for_first_draw")
        self.assertIsNone(before["result"])
        during = analyze_prospective(self.db, date.fromisoformat(before["first_draw"]))
        self.assertEqual(during["status"], "collecting")
        self.assertEqual(during["missing_due_draws"], [before["first_draw"]])
        after = analyze_prospective(self.db, date.fromisoformat(before["final_draw"]))
        self.assertEqual(after["status"], "awaiting_missing_draws")
        self.assertIsNone(after["result"])

    def test_prospective_complete_window_reports_a_fixed_permutation_test(self):
        protocol = load_protocol()
        weights = protocol["white_ball_weights_1_to_69"]
        ranked = sorted(range(1, 70), key=lambda ball: weights[ball - 1])
        october = " ".join(map(str, sorted(ranked[-5:]) + [6]))
        november = " ".join(map(str, sorted(ranked[:5]) + [6]))
        years = protocol["evaluation_years"]
        start, end = date(years[0], 10, 1), date(years[-1], 11, 30)
        days = sorted(day for year in years
                      for day in draw_days(date(year, 10, 1), date(year, 11, 30)))
        body = state_body(*(state_row(day, october if day.month == 10 else november) for day in days))
        store(self.db, "https://example.test/state", body, ny_rows, start, end)
        result = analyze_prospective(self.db, end)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["draws_collected"], len(days))
        self.assertEqual(result["result"]["trials"], protocol["trials"])
        self.assertTrue(result["result"]["evidence_of_alignment"])
        self.assertEqual(result, analyze_prospective(self.db, end))


if __name__ == "__main__":
    unittest.main()
