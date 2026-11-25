"""Full-history Powerball frequency and consecutive-draw tests."""

from datetime import date
from itertools import islice
from math import comb, exp, fsum, lgamma, log, log1p

from .data import START, draw_days
from .stats import RED, WHITE, adjust_holm, frequencies


def binomial_test(observed, trials, probability):
    """Two-sided exact test that includes outcomes at most as likely as observed."""
    log_factorial = lgamma(trials + 1)
    log_p, log_q = log(probability), log1p(-probability)
    masses = [log_factorial - lgamma(k + 1) - lgamma(trials - k + 1)
              + k * log_p + (trials - k) * log_q for k in range(trials + 1)]
    limit = masses[observed] + 1e-10
    return fsum(exp(mass) for mass in masses if mass <= limit) / fsum(map(exp, masses))


def test_count(observed, trials, probability):
    return {"observed": observed, "expected": trials * probability,
            "p_value": binomial_test(observed, trials, probability)}


def analyze_history(db, end):
    rows = db.execute(
        "SELECT draw_date,w1,w2,w3,w4,w5,red FROM powerball "
        "WHERE draw_date BETWEEN ? AND ? ORDER BY draw_date",
        (START.isoformat(), end.isoformat()),
    ).fetchall()
    if not rows:
        raise ValueError("no eligible Powerball draws")
    draws = {date.fromisoformat(row[0]): row[1:] for row in rows}
    expected_dates = sorted(draw_days(START, end))
    unexpected = draws.keys() - set(expected_dates)
    if unexpected:
        raise ValueError(f"Powerball draws outside the official schedule: {sorted(map(str, unexpected))}")

    white_counts, red_counts = frequencies(draws.values())
    whites = [{"number": number, **test_count(white_counts[number], len(rows), 5 / len(WHITE))}
              for number in WHITE]
    reds = [{"number": number, **test_count(red_counts[number], len(rows), 1 / len(RED))}
            for number in RED]

    white_repeats = red_repeats = pairs = 0
    latest_pair = None
    latest = max(draws)
    for previous, current in zip(expected_dates, islice(expected_dates, 1, None)):
        if previous not in draws or current not in draws:
            continue
        pairs += 1
        left, right = draws[previous], draws[current]
        shared = sorted(set(left[:5]).intersection(right[:5]))
        red_repeat = left[5] == right[5]
        white_repeats += bool(shared)
        red_repeats += red_repeat
        if current == latest:
            latest_pair = {"previous_date": previous.isoformat(), "shared_white": shared,
                           "same_powerball": red_repeat}

    white_repeat_probability = 1 - comb(len(WHITE) - 5, 5) / comb(len(WHITE), 5)
    repeat_tests = {
        "at_least_one_white": test_count(white_repeats, pairs, white_repeat_probability),
        "same_powerball": test_count(red_repeats, pairs, 1 / len(RED)),
    } if pairs else {}
    tests = [*whites, *reds, *repeat_tests.values()]
    adjust_holm(tests)

    balls = draws[latest]
    return {
        "through": end.isoformat(),
        "coverage": {"draws": len(rows), "first": rows[0][0], "last": rows[-1][0],
                     "missing": [day.isoformat() for day in expected_dates if day not in draws]},
        "latest_draw": {
            "date": latest.isoformat(),
            "white": [{"number": ball, "previous_count": white_counts[ball] - 1,
                       "current_count": white_counts[ball]} for ball in balls[:5]],
            "powerball": {"number": balls[5], "previous_count": red_counts[balls[5]] - 1,
                          "current_count": red_counts[balls[5]]},
            "consecutive_pair": latest_pair,
        },
        "frequency_tests": {"white": whites, "powerball": reds},
        "consecutive_draw_tests": {"pairs": pairs, **repeat_tests},
        "holm_family_size": len(tests),
    }
