# Project Entropy

## Phase 1 requirements

- Use Python for ingestion, validation, simulation and analysis. Persist data in SQLite.
- Collect official Powerball results starting October 7, 2015, when the 5/69 + 1/26 matrix began.
- Save the draw date, five distinct white balls, red Powerball and published Power Play multiplier. Keep Double Play results in a separate table starting August 23, 2021.
- Retain raw official responses, their request URLs, retrieval times and checksums. Preserve the mapping from accepted draws to source responses.
- Audit schedule coverage, duplicate dates within source responses, invalid values and conflicting results. Never invent a result. Keep conflicting evidence available for review.
- Support incremental updates and a full historical refresh. Use official Eastern Time draw dates and schedule transitions.
- Implement a seedable uniform null control that samples whites without replacement and independently selects the red ball.
- Compare October and November 2026 using observed draw counts and an explicit date cutoff. Document methods and limitations.
- Keep README.md, DEVELOPMENT_LOG.md and automated tests current. Document sources and dependencies.
- Defer predictive machine learning.

Run `python3 -m unittest discover -s tests -v` and `python3 -m entropy audit` after changing ingestion. Regenerate report files when refreshing the delivered snapshot.

## Footage and reporting

- Verify visible main-draw white ball labels against SQLite and use reviewed video annotations for order and rack timing.
- Preserve clip source, SHA-256, camera cohort, normalization, measurement settings and usable frame-pair counts. Keep low-coverage readings missing.
- Summarize timing sensitivity by draw and label findings from reviewed clips as exploratory. Keep broadcast motion in camera-space units.
- Regenerate the JSON and HTML footage reports when changing the bundled evidence.
