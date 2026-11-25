"""Evaluate the frozen October–November Powerball white-ball hypothesis."""

import json
from collections import defaultdict
from datetime import date
from hashlib import sha256
from pathlib import Path
from random import Random

from .data import draw_days

PROTOCOL_PATH = Path(__file__).with_name("oct_nov_protocol.json")
PROTOCOL_SHA256 = "9781ec4e1508ce660edb150dc352ac0f1b9c5cff777514b0baa3b2d79a73981d"


def load_protocol():
    raw = PROTOCOL_PATH.read_bytes()
    if sha256(raw).hexdigest() != PROTOCOL_SHA256:
        raise ValueError("prospective protocol does not match its frozen SHA-256")
    return json.loads(raw)


def analyze_prospective(db, end):
    protocol = load_protocol()
    scheduled = sorted(day for year in protocol["evaluation_years"]
                       for day in draw_days(date(year, 10, 1), date(year, 11, 30)))
    due = {day.isoformat() for day in scheduled if day <= end}
    rows = db.execute(
        "SELECT draw_date,w1,w2,w3,w4,w5 FROM powerball WHERE draw_date BETWEEN ? AND ? "
        "AND substr(draw_date,6,2) IN ('10','11') ORDER BY draw_date",
        (scheduled[0].isoformat(), min(end, scheduled[-1]).isoformat()),
    ).fetchall()
    observed = {row[0] for row in rows}
    if observed - due:
        raise ValueError("prospective data contains an off-schedule draw")
    missing = sorted(due - observed)
    report = {
        "protocol": protocol["id"], "protocol_sha256": PROTOCOL_SHA256,
        "through": end.isoformat(), "first_draw": scheduled[0].isoformat(),
        "final_draw": scheduled[-1].isoformat(), "scheduled_draws": len(scheduled),
        "draws_collected": len(rows), "missing_due_draws": missing,
        "status": "collecting" if end >= scheduled[0] else "waiting_for_first_draw",
        "result": None,
    }
    if end >= scheduled[-1]:
        if missing:
            report["status"] = "awaiting_missing_draws"
        else:
            report["status"] = "complete"
            report["result"] = evaluate(rows, protocol)
    return report


def evaluate(rows, protocol):
    weights = protocol["white_ball_weights_1_to_69"]
    blocks = defaultdict(lambda: ([], []))
    for stamp, *balls in rows:
        day = date.fromisoformat(stamp)
        blocks[(day.year, day.weekday())][day.month - 10].append(
            sum(weights[ball - 1] for ball in balls)
        )
    oct_count = sum(len(october) for october, _ in blocks.values())
    nov_count = sum(len(november) for _, november in blocks.values())
    oct_score = sum(sum(october) for october, _ in blocks.values())
    nov_score = sum(sum(november) for _, november in blocks.values())
    resamples = [(october + november, len(october)) for october, november in blocks.values()]
    rng = Random(protocol["seed"])
    # With fixed group sizes and total score, the mean difference increases with October's sum.
    hits = 0
    for _ in range(protocol["trials"]):
        shuffled_score = sum(sum(rng.sample(pool, count)) for pool, count in resamples)
        hits += shuffled_score >= oct_score
    p_value = (hits + 1) / (protocol["trials"] + 1)
    training = protocol["training_draws"]
    return {
        "october_draws": oct_count, "november_draws": nov_count,
        "alignment_score": (oct_score / oct_count - nov_score / nov_count)
        / (training["october"] * training["november"]),
        "trials": protocol["trials"], "p_value": p_value, "alpha": protocol["alpha"],
        "evidence_of_alignment": p_value < protocol["alpha"],
    }
