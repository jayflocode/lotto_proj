# Development log

## 2026-11-23

- Verified the current matrix, historical schedule and Double Play launch against official Powerball publications.
- Retrieved the New York State open dataset. Its Double Play column supplied 74 draws starting June 3, 2026. Used the official Powerball archive to backfill coverage to August 23, 2021 and reconcile the overlapping rows.
- Implemented separate SQLite tables for both games, response provenance, schedule auditing, input validation, conflict logging and incremental updates.
- Backfilled 1,436 Powerball and 822 Double Play draws through November 21. Every scheduled draw is present for both games. The November 23 Eastern Time draw was still upcoming.
- Implemented seedable uniform sampling and Monte Carlo frequency and permutation tests. No October or November test reached the exploratory 0.05 threshold.
- Ran eight automated tests and a live incremental refresh. The refresh preserved the draw totals and reported no integrity issues.
- Added a full-history baseline for individual ball frequencies and consecutive repeats, with before-and-after counts for the latest draw and Holm-adjusted exact tests. The 1,436-draw snapshot yielded 453 white-ball overlaps and 48 red repeats across 1,435 consecutive pairs. No adjusted test reached the 0.05 threshold.
- Froze the historical October–November white-ball weights before the 2027–2029 evaluation window and added a prospective report with a single fixed final test. The frozen protocol SHA-256 is `9781ec4e1508ce660edb150dc352ac0f1b9c5cff777514b0baa3b2d79a73981d`.

## 2026-11-24

- Refreshed both official result series through November 23 and regenerated the three statistical and integrity snapshots. The database has 1,437 main draws, 823 Double Play draws, and complete scheduled coverage.
- Added checksum verification of preserved response bodies and coverage and Holm adjustments to the October–November report. The refreshed comparison includes 13 October draws and 10 November draws. The between-month raw p-values are 0.224 for white balls and 0.241 for red balls.
- Added reproducible footage extraction and an HTML and JSON report that reconcile footage labels against official main results, reject duplicate recordings, and retain missing readings. Reprocessed six Florida Lottery recordings using matched chamber crops and three window offsets. Both methods saw lower apparent motion at position five than at position two in all six clips at all three offsets. This was a discovery comparison with substantial timing sensitivity in the effect size.
- Added regression coverage for missing and mismatched video records, insufficient measurement coverage, duplicate clips, and changed raw response bytes.
