"""Seeded uniform control and draw-level Monte Carlo tests."""

from collections import Counter
from datetime import date
from random import Random

from .data import draw_days

WHITE = range(1, 70)
RED = range(1, 27)


def uniform_draw(rng):
    return (*sorted(rng.sample(WHITE, 5)), rng.choice(RED))


def frequencies(draws):
    return Counter(ball for draw in draws for ball in draw[:5]), Counter(
        draw[5] for draw in draws
    )


def concentration(counts):
    # Within each pool and sample size, Pearson's statistic is monotone in this sum.
    return tuple(sum(count * count for count in pool.values()) for pool in counts)


def distance(left, right, left_n, right_n):
    # Integer numerator of squared differences of per-draw inclusion rates.
    return tuple(sum((a[ball] * right_n - b[ball] * left_n) ** 2 for ball in support)
                 for a, b, support in zip(left, right, (WHITE, RED)))


def monte_carlo(observed, trials):
    hits = [0, 0]
    count = 0
    for simulated in trials:
        count += 1
        for i in range(2):
            hits[i] += simulated[i] >= observed[i]
    return dict(zip(("white", "powerball"), ((h + 1) / (count + 1) for h in hits)))


def adjust_holm(tests):
    adjusted = 0.0
    for rank, test in enumerate(sorted(tests, key=lambda row: row["p_value"])):
        adjusted = max(adjusted, min(1.0, (len(tests) - rank) * test["p_value"]))
        test["holm_p_value"] = adjusted


def analyze(db, end, trials=20000, seed=20261123):
    if trials < 1:
        raise ValueError("trials must be positive")
    rng = Random(seed)
    groups = []
    result = {"through": str(end), "trials": trials, "seed": seed}
    for month, last_day in (("2026-10", 31), ("2026-11", 30)):
        rows = db.execute(
            "SELECT draw_date,w1,w2,w3,w4,w5,red,multiplier FROM powerball "
            "WHERE substr(draw_date,1,7)=? AND draw_date<=? ORDER BY draw_date",
            (month, str(end)),
        ).fetchall()
        expected = {day.isoformat() for day in draw_days(
            date.fromisoformat(month + "-01"), min(end, date.fromisoformat(f"{month}-{last_day}"))
        )}
        observed_dates = {row[0] for row in rows}
        off_schedule = sorted(observed_dates - expected)
        if off_schedule:
            raise ValueError(f"unexpected draw dates for {month}: {off_schedule}")
        draws = [row[1:7] for row in rows]
        if not draws:
            raise ValueError(f"no eligible Powerball draws for {month}")
        groups.append(draws)
        observed = concentration(frequencies(draws))
        result[month] = {
            "draws": len(draws), "first": rows[0][0], "last": rows[-1][0],
            "scheduled_draws_through_cutoff": len(expected),
            "missing_draw_dates": sorted(expected - observed_dates),
            "power_play_counts": dict(sorted(Counter(row[-1] for row in rows).items())),
            "mean_white_sum": sum(sum(draw[:5]) for draw in draws) / len(draws),
            "mean_powerball": sum(draw[5] for draw in draws) / len(draws),
            "uniform_p": monte_carlo(observed, (
                concentration(frequencies([uniform_draw(rng) for _ in draws]))
                for _ in range(trials)
            )),
        }
    october, november = groups
    a, b = len(october), len(november)
    pool = october + november

    def permuted():
        shuffled = rng.sample(pool, len(pool))
        return distance(frequencies(shuffled[:a]), frequencies(shuffled[a:]), a, b)

    observed = distance(frequencies(october), frequencies(november), a, b)
    result["between_months_p"] = monte_carlo(observed, (permuted() for _ in range(trials)))
    raw = {month: result[month]["uniform_p"] for month in ("2026-10", "2026-11")}
    raw["between_months"] = result["between_months_p"]
    tests = [{"comparison": name, "pool": pool, "p_value": value}
             for name, values in raw.items() for pool, value in values.items()]
    adjust_holm(tests)
    result["holm_family_size"] = len(tests)
    result["holm_adjusted_p"] = {name: {} for name in raw}
    for test in tests:
        result["holm_adjusted_p"][test["comparison"]][test["pool"]] = test["holm_p_value"]
    return result
