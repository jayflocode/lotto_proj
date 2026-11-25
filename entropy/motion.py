"""Validate and summarize one camera cohort of main Powerball footage."""

import json
from datetime import date
from hashlib import sha256
from math import isfinite
from pathlib import Path
from statistics import median
from urllib.parse import urlsplit

from .data import START, draw_days, scheduled

DEFAULT_EVIDENCE = Path(__file__).resolve().parent.parent / "evidence" / "powerball-motion.json"
METHODS = ("dis", "farneback")
WINDOWS = {"early": -0.25, "nominal": 0, "late": 0.25}
WINDOW_DURATION = 1.5
WINDOW_END_BEFORE_RACK = 0.7
MIN_USABLE_FRACTION = 0.5


def window_bounds(arrival, shift):
    end = round(arrival - WINDOW_END_BEFORE_RACK + shift, 6)
    return round(end - WINDOW_DURATION, 6), end


def valid_number(value):
    return type(value) in (float, int) and isfinite(value)


def validate_geometry(metadata):
    width, height = metadata["frame_size_px"]
    x0, y0, x1, y1 = metadata["crop"]
    chamber_width = metadata["chamber_width_px"]
    start = metadata["decode_start_s"]
    duration = metadata["decode_duration_s"]
    if (any(type(value) is not int for value in (width, height, x0, y0, x1, y1))
            or not 0 <= x0 < x1 <= width or not 0 <= y0 < y1 <= height
            or min(x1 - x0, y1 - y0) < 35 or not valid_number(chamber_width)
            or not x1 - x0 <= chamber_width <= width):
        raise ValueError("invalid chamber crop or width")
    if not valid_number(start) or start < 0 or not valid_number(duration) or duration < WINDOW_DURATION:
        raise ValueError("invalid decoding interval")


def validate_evidence(evidence):
    if (evidence["schema_version"] != 1 or evidence["game"] != "powerball"
            or not evidence["camera_cohort"] or not evidence["source_publisher"]
            or not evidence["software"]):
        raise ValueError("expected version 1 main Powerball footage from one camera cohort")
    validate_geometry(evidence)
    first = evidence["decode_start_s"]
    last = first + evidence["decode_duration_s"]
    seen_dates = set()
    seen_sources = set()
    seen_hashes = set()
    for clip in evidence["clips"]:
        day = date.fromisoformat(clip["date"])
        source = urlsplit(clip["url"])
        digest = clip["sha256"]
        fps = clip["fps"]
        if (day.isoformat() != clip["date"] or day < START or not scheduled(day)
                or day in seen_dates or source.scheme != "https" or not source.netloc
                or clip["url"] in seen_sources or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)
                or digest in seen_hashes or not valid_number(fps) or fps <= 0):
            raise ValueError(f"invalid or duplicate footage provenance for {day}")
        seen_dates.add(day)
        seen_sources.add(clip["url"])
        seen_hashes.add(digest)
        balls = clip["white_in_order"]
        arrivals = clip["rack_arrival_s"]
        if (len(balls) != 5 or any(type(ball) is not int or not 1 <= ball <= 69 for ball in balls)
                or len(set(balls)) != 5 or len(arrivals) != 5
                or any(not valid_number(t) or not first <= t < last + WINDOW_END_BEFORE_RACK
                       for t in arrivals)
                or any(a >= b for a, b in zip(arrivals, arrivals[1:]))):
            raise ValueError(f"invalid draw order or rack timestamps for {day}")
        measurements = clip["measurements"]
        if set(measurements) != set(WINDOWS):
            raise ValueError(f"missing timing variant for {day}")
        for name, shift in WINDOWS.items():
            records = measurements[name]
            if len(records) != 5:
                raise ValueError(f"expected five measurement windows for {day}")
            for arrival, record in zip(arrivals, records):
                start, end = window_bounds(arrival, shift)
                expected = record["frame_pairs"]
                if (not first <= start < end <= last or type(expected) is not int
                        or expected < 1 or abs(expected - fps * WINDOW_DURATION) > 1.01):
                    raise ValueError(f"invalid measurement window for {day}")
                for method in METHODS:
                    count = record[method]["usable_pairs"]
                    value = record[method]["chamber_widths_per_s"]
                    if (type(count) is not int or not 0 <= count <= expected
                            or (value is None) != (count < expected * MIN_USABLE_FRACTION)
                            or (value is not None and (not valid_number(value) or value < 0))):
                        raise ValueError(f"invalid {method} reading for {day}")


def analyze_motion(db, end, evidence_path=DEFAULT_EVIDENCE):
    raw = Path(evidence_path).read_bytes()
    try:
        evidence = json.loads(raw)
        validate_evidence(evidence)
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"malformed footage evidence: {error}") from error
    clips = sorted(evidence["clips"], key=lambda clip: clip["date"])
    verified = []
    excluded = []
    eligible = [clip for clip in clips if clip["date"] <= end.isoformat()]
    for clip in eligible:
        day = clip["date"]
        official = db.execute(
            "SELECT w1,w2,w3,w4,w5 FROM powerball WHERE draw_date = ?", (day,)
        ).fetchone()
        if official is None or list(official) != sorted(clip["white_in_order"]):
            excluded.append({"date": day, "url": clip["url"],
                             "reason": "missing_official_draw" if official is None else "white_ball_mismatch"})
            continue
        verified.append(clip)

    phase_comparison = []
    for name, shift in WINDOWS.items():
        differences = {}
        for clip in verified:
            windows = clip["measurements"][name]
            before_second, before_fifth = windows[1], windows[4]
            values = [reading[method]["chamber_widths_per_s"]
                      for method in METHODS for reading in (before_second, before_fifth)]
            if None not in values:
                differences[clip["date"]] = {
                    method: round(fifth - second, 6)
                    for method, second, fifth in zip(METHODS, values[::2], values[1::2])
                }
        phase_comparison.append({
            "window": name, "shift_s": shift, "eligible_draws": len(differences),
            "fifth_lower_both_methods": sum(max(row.values()) < 0 for row in differences.values()),
            "ineligible_dates": [clip["date"] for clip in verified if clip["date"] not in differences],
            "median_fifth_minus_second": {
                method: round(median(row[method] for row in differences.values()), 6)
                if differences else None for method in METHODS
            },
            "fifth_minus_second_by_date": differences,
        })
    first_date = clips[0]["date"] if clips else None
    scheduled_dates = draw_days(date.fromisoformat(first_date), end) if first_date else set()
    available_dates = {clip["date"] for clip in eligible}
    return {
        "through": end.isoformat(), "camera_cohort": evidence["camera_cohort"],
        "evidence_sha256": sha256(raw).hexdigest(),
        "measurement_metadata": {
            field: evidence[field] for field in
            ("source_publisher", "software", "frame_size_px", "crop", "chamber_width_px",
             "decode_start_s", "decode_duration_s")
        },
        "coverage": {"first_candidate_date": first_date,
                     "footage_draws": len(eligible), "verified_draws": len(verified),
                     "missing_footage_dates": sorted(day.isoformat() for day in scheduled_dates
                                                     if day.isoformat() not in available_dates),
                     "excluded": excluded},
        "window_rule": {"duration_s": WINDOW_DURATION,
                        "nominal_end_before_rack_s": WINDOW_END_BEFORE_RACK,
                        "min_usable_fraction": MIN_USABLE_FRACTION},
        "unit": "apparent chamber widths per second",
        "phase_comparison": phase_comparison,
        "interpretation": "Exploratory draw-level comparison selected after viewing these clips. "
                          "Official results verify the five labels. Draw order and timing come from footage. "
                          "Both methods use the same frames. The motion readings include effects of chamber occupancy and camera perspective.",
        "draws": verified,
    }
