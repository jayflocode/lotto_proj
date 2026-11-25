# Project Entropy

Project Entropy is a Python and SQLite research project that compares official Powerball results with a uniform random control. It also measures visible chamber motion in drawing footage to investigate which patterns recur across draws.

The project archives official results and their source responses, audits data quality, and produces reproducible statistical and footage reports. Phase 1 focuses on measurement and hypothesis testing.

## Quick start

From the repository root, use Python 3.9 or later with SQLite support and IANA time zone data. The core commands and tests use the Python standard library.

```sh
python3 -m entropy audit --through 2026-11-23
python3 -m entropy simulate --draws 3 --seed 42
python3 -m unittest discover -s tests -v
```

The default database is `entropy.sqlite` in the current directory. Run `python3 -m entropy update` to fetch recent results and recover scheduled gaps. Use `--db` before the subcommand to choose a database. This command rebuilds the documented snapshot from the public sources and requires internet access.

```sh
python3 -m entropy --db rebuilt.sqlite update --full --through 2026-11-23
```

`--through` is an inclusive Eastern Time date. When omitted, date-based commands use the latest elapsed scheduled draw time. A result awaiting publication appears as missing until it is retrieved.

## Data snapshot

| Game | First draw | Last draw | Records | Scheduled gaps |
| --- | --- | --- | ---: | ---: |
| Powerball | 2015-10-07 | 2026-11-23 | 1,437 | 0 |
| Double Play | 2021-08-23 | 2026-11-23 | 823 | 0 |

The audit found no duplicate dates, invalid values, conflicting results, or off-schedule records. SQLite integrity and foreign-key checks passed, and all 60 archived response bodies matched their stored SHA-256 hashes. [Audit results](INTEGRITY.json)

## Analysis

| Command | What it measures |
| --- | --- |
| `analyze --through 2026-11-23` | Monte Carlo frequency tests against the uniform control and a whole-draw permutation comparison of October and November 2026, with Holm adjustment across six tests |
| `history --through 2026-11-23` | Exact tests for individual ball frequencies and consecutive-draw repeats across the full history, with Holm adjustment |
| `prospective` | Coverage for the frozen October–November white-ball hypothesis, with one final test after the 2027–2029 evaluation window is complete |
| `simulate --draws 3 --seed 42` | Reproducible control draws with five distinct white balls sampled uniformly from 1–69 and an independent red Powerball sampled uniformly from 1–26 |

Prepend `python3 -m entropy` to each command. The October–November comparison used 13 October draws and 10 November draws through November 23. The between-month raw p-values were 0.224 for white balls and 0.241 for the red ball. None of the six exploratory tests reached the 0.05 threshold. The seasonal sample is small, so subtle deviations could go undetected. [Seasonal results](ANALYSIS.json) · [Full-history results](HISTORY.json) · [Frozen protocol](entropy/oct_nov_protocol.json)

## Footage analysis

The footage module matches the five white-ball labels to official SQLite results and uses the recording for draw order and rack-arrival timing. It saves the source URL, clip hash, crop, frame rate, and usable frame counts. Two optical-flow methods estimate apparent motion in chamber widths per second. The nominal 1.5-second window ends 0.7 seconds before each estimated rack arrival. The report checks shifts of a quarter second in both directions.

In the six November 11–23 recordings, both methods measured less apparent motion before the fifth white ball reached the rack than before the second across the three tested timings. The size of the difference varied with the timing and method. The comparison was chosen after reviewing these clips. Camera perspective and the number of balls remaining in the chamber can affect the measurements. Testing whether the pattern recurs requires fresh footage. Estimating physical ball speed requires camera calibration and depth information. [Footage data](MOTION.json) · [Video sources and timing annotations](evidence/powerball-motion-manifest.json)

Generate a standalone report and open it in a browser.

```sh
python3 -m entropy motion --through 2026-11-23 --html > motion-report.html
```

Extracting measurements from local video copies requires a Python environment with NumPy and OpenCV. The bundled measurements were generated with NumPy 2.4.6 and OpenCV 5.1.0 on 640 × 360 recordings at 30 fps. Use clips that match the manifest framing and verify that the frame spacing is constant.

```sh
python3 -m pip install numpy opencv-python-headless
python3 -m entropy motion-extract \
  --manifest evidence/powerball-motion-manifest.json \
  --videos-dir /path/to/local/videos > motion-evidence.json
python3 -m entropy motion --through 2026-11-23 --evidence motion-evidence.json
```

## Sources and storage

- **New York State Lottery.** Historical main results, Power Play multipliers, and available Double Play results. [Open dataset](https://data.ny.gov/Government-Finance/Lottery-Powerball-Winning-Numbers-Beginning-2010/d6yy-54nr/about_data) · [JSON endpoint](https://data.ny.gov/resource/d6yy-54nr.json)
- **Powerball.** Recent main-result cross-checks, scheduled gap recovery, and Double Play backfill. [Main archive](https://www.powerball.com/previous-results) · [Double Play archive](https://www.powerball.com/previous-results?gc=pb-double-play) · [Monday and Double Play launch](https://www.powerball.com/powerball-debuts-new-monday-drawing-double-play-feature-next-week)
- **Florida Lottery.** Official broadcast recordings used for the motion analysis. The manifest lists the individual video links. [Footage manifest](evidence/powerball-motion-manifest.json)

SQLite stores main and Double Play draws separately. Each accepted draw refers to a preserved source response with its request URL, UTC retrieval time, and SHA-256 fingerprint. The updater rechecks the most recent 49 calendar dates and goes back farther when it finds scheduled gaps. Source conflicts are logged for review and the first accepted result remains in place.

The SQLite snapshot includes copies of upstream response bodies. For a public upload, check the source terms for redistribution or generate the snapshot locally from the endpoints above. [Open NY terms](https://data.ny.gov/dataset/OPEN-NY-Terms-Of-Use/77gx-ii52)

## Project layout

| Path | Contents |
| --- | --- |
| [`entropy/`](entropy/) | CLI, SQLite ingestion, statistical tests, and footage analysis |
| [`evidence/`](evidence/) | Source manifest and extracted footage measurements |
| [`tests/`](tests/) | Automated tests |
| [`DEVELOPMENT_LOG.md`](DEVELOPMENT_LOG.md) | Implementation and snapshot history |
| [`AGENTS.md`](AGENTS.md) | Project requirements and verification commands |
