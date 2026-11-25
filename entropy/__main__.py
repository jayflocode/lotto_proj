"""Command-line entry point for Project Entropy."""

import argparse
import json
from contextlib import closing
from datetime import date
from random import Random

from .data import START, audit, connect, cutoff, update
from .history import analyze_history
from .motion import DEFAULT_EVIDENCE, analyze_motion
from .prospective import analyze_prospective
from .stats import analyze, uniform_draw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="entropy.sqlite")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("update", "audit", "analyze", "history", "prospective", "motion"):
        command = commands.add_parser(name)
        command.add_argument("--through", type=date.fromisoformat,
                             help="inclusive cutoff, defaults to latest elapsed ET draw time")
        if name == "update":
            command.add_argument("--full", action="store_true")
        if name == "analyze":
            command.add_argument("--trials", type=int, default=20000)
            command.add_argument("--seed", type=int, default=20261123)
        if name == "motion":
            command.add_argument("--evidence", default=DEFAULT_EVIDENCE,
                                 help="validated footage measurements JSON")
            command.add_argument("--html", action="store_true", help="render a standalone HTML report")
    extractor = commands.add_parser("motion-extract", help="measure local constant-rate draw recordings")
    extractor.add_argument("--manifest", required=True)
    extractor.add_argument("--videos-dir", required=True)
    simulate = commands.add_parser("simulate")
    simulate.add_argument("--draws", type=int, default=1)
    simulate.add_argument("--seed", type=int)
    args = parser.parse_args()
    if args.command == "simulate":
        if args.draws < 1:
            parser.error("--draws must be positive")
        rng = Random(args.seed)
        print(json.dumps([{"white": balls[:5], "powerball": balls[-1]}
                          for balls in (uniform_draw(rng) for _ in range(args.draws))], indent=2))
        return 0
    if args.command == "motion-extract":
        try:
            from .motion_extract import extract
        except ImportError:
            parser.error("motion extraction requires numpy and opencv-python-headless")
        try:
            report = extract(args.manifest, args.videos_dir)
        except (OSError, ValueError, TypeError, KeyError) as error:
            parser.error(str(error))
        print(json.dumps(report, indent=2, allow_nan=False))
        return 0
    end = args.through or cutoff()
    if end < START or end > cutoff():
        parser.error("--through must be between 2015-10-07 and the latest elapsed ET drawing")
    with closing(connect(args.db)) as db:
        if args.command in ("analyze", "history", "prospective", "motion"):
            try:
                if args.command == "history":
                    report = analyze_history(db, end)
                elif args.command == "prospective":
                    report = analyze_prospective(db, end)
                elif args.command == "motion":
                    report = analyze_motion(db, end, args.evidence)
                else:
                    report = analyze(db, end, args.trials, args.seed)
            except (OSError, ValueError) as error:
                parser.error(str(error))
        elif args.command == "update":
            report = update(db, end, args.full)
        else:
            report = audit(db, end)
    if args.command == "motion" and args.html:
        from .motion_view import render_motion
        print(render_motion(report))
    else:
        print(json.dumps(report, indent=2))
    if args.command in ("update", "audit"):
        return int(bool(report["source_issues"] or report["raw_checksum_mismatches"]
                        or report["foreign_key_violations"]
                        or report["sqlite_integrity"] != "ok"
                        or any(report[game][key] for game in ("powerball", "double_play")
                               for key in ("missing", "off_schedule"))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
