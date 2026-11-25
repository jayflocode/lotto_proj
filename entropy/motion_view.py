"""Render the footage report as a self-contained HTML page."""

from html import escape

from .motion import METHODS, window_bounds


def reading(value, signed=False):
    if value is None:
        return "—"
    return f"{value:+.4f}" if signed else f"{value:.4f}"


def render_motion(report):
    coverage = report["coverage"]
    verified = coverage["verified_draws"]
    nominal = next(row for row in report["phase_comparison"] if row["window"] == "nominal")
    shifts = []
    for row in report["phase_comparison"]:
        dis, farneback = (reading(row["median_fifth_minus_second"][method], signed=True)
                          for method in METHODS)
        shifts.append(
            f'<tr><th scope="row">{row["shift_s"]:+.2f} s</th>'
            f'<td>{row["fifth_lower_both_methods"]} / {row["eligible_draws"]}</td>'
            f"<td>{dis}</td><td>{farneback}</td></tr>"
        )

    details = []
    for clip in report["draws"]:
        rows = []
        for i, (ball, arrival) in enumerate(zip(clip["white_in_order"], clip["rack_arrival_s"]), 1):
            start, end = window_bounds(arrival, 0)
            data = clip["measurements"]["nominal"][i - 1]
            columns = "".join(
                f'<td>{reading(data[method]["chamber_widths_per_s"])}'
                f'<small>{data[method]["usable_pairs"]}/{data["frame_pairs"]} frame pairs</small></td>'
                for method in METHODS
            )
            rows.append(f'<tr><th scope="row">{i}</th><td>{ball:02d}</td><td>{arrival:.2f} s</td>'
                        f'<td>{start:.2f}–{end:.2f} s</td>{columns}</tr>')
        balls = " · ".join(f"{ball:02d}" for ball in clip["white_in_order"])
        details.append(f"""<details><summary><time>{escape(clip["date"])}</time>
        <span class="balls">{balls}</span></summary>
        <div class="table-scroll"><table><caption>Nominal measurement windows</caption><thead><tr>
        <th scope="col">Position</th><th scope="col">Ball</th><th scope="col">Rack arrival</th>
        <th scope="col">Video window</th><th scope="col">DIS</th><th scope="col">Farnebäck</th>
        </tr></thead><tbody>{''.join(rows)}</tbody></table></div>
        <p><a href="{escape(clip['url'], quote=True)}">Official draw video</a></p></details>""")

    missing_dates = coverage["missing_footage_dates"]
    missing = ('<details><summary>Missing footage dates</summary><p>'
               + escape(", ".join(missing_dates)) + '</p></details>') if missing_dates else ""
    excluded = ""
    if coverage["excluded"]:
        rows = "".join(f'<li>{escape(row["date"])} · {escape(row["reason"].replace("_", " "))}</li>'
                       for row in coverage["excluded"])
        excluded = f"<details><summary>Excluded clips</summary><ul>{rows}</ul></details>"

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Project Entropy | Powerball footage</title>
<style>
:root {{color-scheme:light;--ink:#152e31;--paper:#f3f6ef;--line:#c4d1c7;--accent:#116353}}
* {{box-sizing:border-box}}
body {{margin:0;color:var(--ink);background:var(--paper);font:16px/1.6 system-ui,sans-serif}}
main {{width:min(100% - 2rem, 62rem);margin:0 auto;padding:2.5rem 0}}
header {{padding:1.7rem 2rem;background:#123b37;color:#f3f6ef;border-radius:.7rem}}
h1 {{font:clamp(2rem,5vw,3.5rem)/1.03 Georgia,serif;margin:.35rem 0 .85rem}}
h2 {{font:1.75rem Georgia,serif;margin:0}}
header p {{margin:.3rem 0}}
section {{margin:1.5rem 0;padding:1.35rem clamp(.7rem,3vw,1.5rem);border:1px solid var(--line);
background:#fcfdf9;border-radius:.6rem}}
.table-scroll {{overflow-x:auto}}
table {{width:100%;border-collapse:collapse;text-align:right;font-variant-numeric:tabular-nums}}
caption {{text-align:left;padding:.65rem 0}}
th,td {{padding:.65rem .5rem;border-bottom:1px solid var(--line);white-space:nowrap}}
th:first-child {{text-align:left}}
details {{border-top:1px solid var(--line);padding:.5rem 0}}
summary {{cursor:pointer;padding:.3rem 0;font-weight:650}}
.balls {{margin-left:.7rem;color:var(--accent);font-variant-numeric:tabular-nums}}
small {{display:block;color:#455d58}}
a {{color:var(--accent)}}
a:focus-visible,summary:focus-visible {{outline:2px solid var(--accent);outline-offset:4px}}
</style></head>
<body><main>
<header><p>Project Entropy · Footage through {escape(report["through"])}</p>
<h1>Powerball chamber motion</h1><p>{escape(report["camera_cohort"])}</p></header>
<section><h2>Timing sensitivity</h2>
<p><strong>{nominal["fifth_lower_both_methods"]} of {nominal["eligible_draws"]} eligible draws</strong>
showed lower motion before ball five than before ball two using both methods in the nominal window.</p>
<p>Each window lasts 1.5 seconds and nominally ends 0.7 seconds before the estimated rack arrival.
The table shows the median within-draw difference in apparent chamber widths per second.</p>
<div class="table-scroll"><table><thead><tr><th scope="col">Window shift</th>
<th scope="col">Lower in both methods</th><th scope="col">DIS difference</th>
<th scope="col">Farnebäck difference</th></tr></thead><tbody>{''.join(shifts)}</tbody></table></div>
<p>{escape(report["interpretation"])}</p></section>
<section><h2>Draw evidence</h2>
<p>{verified} verified clips · {len(coverage["excluded"])} excluded · {len(missing_dates)} missing dates</p>
{missing}{excluded}{''.join(details)}</section>
</main></body></html>
"""
