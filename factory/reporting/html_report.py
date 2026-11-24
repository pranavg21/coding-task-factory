"""Static, self-contained HTML audit report (report/index.html), built only from collected outputs."""
from __future__ import annotations

import html
from collections import Counter
from pathlib import Path
from typing import Any

from factory.schemas import ChangePattern, TaskType

CSS = """
:root{--ink:#15202b;--muted:#5b6672;--line:#d8dee6;--blue:#176eb8;--orange:#c8701f;--green:#1e7a46;--red:#b3261e;--bg:#f6f8fb}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,Segoe UI,sans-serif}
main{max-width:1180px;margin:0 auto;padding:28px 18px 60px}h1{margin:0 0 4px;font-size:26px}h2{margin:34px 0 10px;font-size:19px}
.sub{color:var(--muted);margin:0 0 20px}.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.kpi{background:#fff;border:1px solid var(--line);border-radius:10px;padding:12px 14px}.kpi b{display:block;font-size:24px}
.kpi span{color:var(--muted);font-size:13px}table{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;font-size:13.5px;vertical-align:top}th{background:#eef2f7}
.ok{color:var(--green);font-weight:600}.bad{color:var(--red);font-weight:600}.tag{display:inline-block;padding:1px 7px;border-radius:9px;font-size:12px;background:#eef2f7}
.gold{background:#fbefe4;color:#8a4a0c}.heat td{text-align:center;width:9%}.note{color:var(--muted);font-size:13px}
.wrap{overflow-x:auto}code{font-size:12.5px}
"""


def _e(v: Any) -> str:
    return html.escape(str(v))


def _kpi(value: Any, label: str) -> str:
    return f'<div class="kpi"><b>{_e(value)}</b><span>{_e(label)}</span></div>'


def generate_html_report(data: dict[str, Any], output_html: Path) -> Path:
    tasks, funnel, runs = data.get("tasks", []), data.get("funnel", []), data.get("runs", [])
    generated = [t for t in tasks if not t["gold"]]
    accepted = [t for t in generated if t["accepted"]]
    rejected = Counter(e["final_stage"] for e in funnel if e["status"] == "rejected")
    mutants = sum(t["mutants"] or 0 for t in tasks)
    caught = sum(t["caught"] or 0 for t in tasks)
    cost = sum(e.get("cost_usd", 0) for e in funnel)
    per_task = f"${cost / len(accepted):.2f}" if accepted else "—"
    rows = []
    for t in tasks:
        status = '<span class="ok">ACCEPTED</span>' if t["accepted"] else '<span class="bad">REJECTED</span>'
        kind = '<span class="tag gold">gold (hand-built)</span>' if t["gold"] else '<span class="tag">generated</span>'
        strength = "—" if t["mutants"] is None else f'{t["caught"]}/{t["mutants"]}'
        surv = "<br>".join(f"<code>{_e(s)}</code>" for s in t["survivors"])
        v = t["variety"]
        rows.append(f"<tr><td><b>{_e(t['task_id'])}</b><br>{_e(t['title'])}<br>{kind}</td><td>{_e(t['repo_id'])}<br>"
                    f"<code>{_e(t['pinned'])}</code> · {_e(t['framework'])}</td><td>{_e(v.get('task_type', ''))}<br>"
                    f"{_e(v.get('change_pattern', ''))}<br>{_e(v.get('scope', ''))}</td><td>{t['fail_to_pass']}</td>"
                    f"<td>{t['pass_to_pass']:,}</td><td>{t['runs_passed']}/{t['runs']} · flaky {t['flaky']}</td>"
                    f"<td>{status}</td><td>{strength}<br>{surv}</td></tr>")
    patterns = [p.value for p in ChangePattern]
    types = [t.value for t in TaskType]
    counts = Counter((t["variety"].get("task_type"), t["variety"].get("change_pattern")) for t in tasks if t["accepted"])
    peak = max(counts.values(), default=1)
    heat = "".join(
        f"<tr><th>{_e(tt)}</th>" + "".join(
            f'<td style="background:rgba(23,110,184,{0.12 + 0.6 * counts[(tt, p)] / peak if counts[(tt, p)] else 0})">'
            f"{counts[(tt, p)] or ''}</td>" for p in patterns) + "</tr>" for tt in types)
    funnel_rows = "".join(f"<tr><td>{_e(stage)}</td><td>{n}</td></tr>" for stage, n in rejected.most_common())
    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Coding Task Factory — audit report</title><style>{CSS}</style></head><body><main>
<h1>Coding Task Factory — audit report</h1>
<p class="sub">Every number below is read from the task packages, funnel and run records in the output folders. Gold tasks are hand-built references and are not counted as factory output.</p>
<div class="kpis">{_kpi(len(funnel), "candidates (generated)")}{_kpi(len(accepted), "accepted (generated)")}
{_kpi(sum(rejected.values()), "rejected, with reasons")}{_kpi(sum(1 for t in tasks if t['gold'] and t['accepted']), "gold tasks proven")}
{_kpi(f"{caught}/{mutants}" if mutants else "—", "planted bugs caught")}{_kpi(sum(t['flaky'] for t in tasks), "flaky tests")}
{_kpi(per_task, "model cost per accepted task")}{_kpi(data.get("manual_edits", "—"), "manual edits to outputs (manual_interventions.json)")}</div>
<h2>Tasks and the 3-condition proof</h2>
<p class="note">Condition 1: untouched repository passes every PASS_TO_PASS test. Condition 2: with the reference patch, every test passes. Condition 3: without it, every new test fails. Each task ran all three on 3 fresh copies; any test whose result changed between runs rejects the task.</p>
<div class="wrap"><table><tr><th>Task</th><th>Repository</th><th>Variety cell</th><th>New tests</th><th>Existing tests</th><th>Runs passed</th><th>Verdict</th><th>Planted bugs caught / survivors</th></tr>{''.join(rows) or '<tr><td colspan="8">No tasks yet.</td></tr>'}</table></div>
<h2>Rejection funnel (generated candidates)</h2>
<div class="wrap"><table><tr><th>Stage that rejected</th><th>Candidates</th></tr>{funnel_rows or '<tr><td colspan="2">No rejections recorded yet.</td></tr>'}</table></div>
<h2>Variety coverage (accepted tasks)</h2>
<div class="wrap"><table class="heat"><tr><th></th>{''.join(f'<th>{_e(p.replace("_", " "))}</th>' for p in patterns)}</tr>{heat}</table></div>
<h2>Runs</h2>
<div class="wrap"><table><tr><th>Repository</th><th>Pinned</th><th>Seed</th><th>Accepted / target</th><th>API calls</th><th>Cost</th><th>Runtime</th></tr>
{''.join(f"<tr><td>{_e(r['repo_id'])}</td><td><code>{_e(r['pinned_version'][:7])}</code></td><td>{r['seed']}</td><td>{r['accepted']}/{r['target']}</td><td>{r['api_calls']}</td><td>${r['cost_usd']}</td><td>{r['runtime_sec']}s</td></tr>" for r in runs) or '<tr><td colspan="7">No generation runs recorded yet.</td></tr>'}</table></div>
</main></body></html>"""
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_html.write_text(doc, encoding="utf-8", newline="\n")
    return output_html
