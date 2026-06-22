"""HTML report dashboard.

Renders a backtest report as a self contained HTML page: the headline with versus
without memory comparison, the per task per axis breakdown, and the supporting
statistics. No templating dependency and no external assets, so the page is a single
file that opens anywhere, which is the right shape for a take home demo artifact.
"""

from __future__ import annotations

from ..eval.reports import summarize
from ..eval.runner import BacktestReport


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def render_html(report: BacktestReport, *, title: str = "ombench backtest") -> str:
    """Render a backtest report as a self contained HTML page."""
    s = summarize(report)
    rows = []
    for r in report.results:
        wo = r.without_memory.scores
        wm = r.with_memory.scores
        cls = "win" if r.total_delta > 0 else ("same" if r.total_delta == 0 else "loss")
        rows.append(
            f"<tr class='{cls}'><td>{_esc(r.task_id)}</td>"
            f"<td>{wo.task_outcome}</td><td>{wm.task_outcome}</td>"
            f"<td>{wm.memory_retrieval}</td><td>{wm.memory_application}</td>"
            f"<td>{wm.action_validity}</td><td>{r.total_delta}</td></tr>"
        )
    rows_html = "\n".join(rows)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{_esc(title)}</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; margin: 2rem; color: #1a1a1a; }}
  h1 {{ font-size: 1.4rem; }}
  table {{ border-collapse: collapse; margin-top: 1rem; width: 100%; }}
  th, td {{ border: 1px solid #ddd; padding: 6px 10px; text-align: left; font-size: 0.9rem; }}
  th {{ background: #f4f1ea; }}
  tr.win td {{ background: #eaf7ea; }}
  tr.loss td {{ background: #fdeaea; }}
  .headline {{ font-size: 1.1rem; margin: 1rem 0; }}
  .stat {{ color: #555; }}
</style>
</head>
<body>
<h1>{_esc(title)}</h1>
<p class="headline">Mean rubric total
  <b>{s['mean_total_without']}</b> without memory &rarr;
  <b>{s['mean_total_with']}</b> with memory
  (delta <b>{s['mean_delta']}</b>).</p>
<p class="stat">Success rate {s['success_without']} &rarr; {s['success_with']};
  win rate {s['win_rate']} (CI [{s['win_rate_ci'][0]}, {s['win_rate_ci'][1]}]);
  mean delta 95% CI [{s['delta_ci'][0]}, {s['delta_ci'][1]}];
  Wilcoxon p {s['wilcoxon_p']} ({s['wilcoxon_method']}).</p>
<table>
  <thead><tr>
    <th>task</th><th>outcome w/o</th><th>outcome w/</th>
    <th>retrieval w/</th><th>application w/</th><th>validity w/</th><th>delta</th>
  </tr></thead>
  <tbody>
{rows_html}
  </tbody>
</table>
</body>
</html>
"""
