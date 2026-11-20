"""Render a session into a self-contained HTML report and a JUnit XML file."""

from __future__ import annotations

import base64
import json
import os
from html import escape
from typing import Any, Dict, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape as xml_escape

from . import __version__

MAX_EMBED_BYTES = 400 * 1024
MAX_EMBEDS = 24

KIND_COLORS = {
    "java_crash": "#e05263",
    "native_crash": "#d97706",
    "anr": "#7c3aed",
    "process_death": "#0f766e",
    "low_memory": "#b45309",
    "exception": "#be123c",
}

CSS = """
:root{--bg:#0d1117;--panel:#161b22;--panel2:#1c2330;--line:#2a3140;--text:#e6edf3;--muted:#8b949e;
--accent:#58a6ff;--good:#3fb950;--bad:#f85149;--warn:#d29922;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 "Segoe UI",Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:28px 20px 60px}
header{display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between;
border-bottom:1px solid var(--line);padding-bottom:18px;margin-bottom:24px}
h1{font-size:22px;margin:0;font-weight:650;letter-spacing:.2px}
h1 small{display:block;font-size:12px;color:var(--muted);font-weight:400;margin-top:4px}
h2{font-size:15px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:34px 0 12px}
.badge{padding:5px 12px;border-radius:999px;font-size:12px;font-weight:700;text-transform:uppercase;
letter-spacing:.06em}
.badge.bad{background:rgba(248,81,73,.15);color:#ff7b72;border:1px solid rgba(248,81,73,.4)}
.badge.good{background:rgba(63,185,80,.12);color:#56d364;border:1px solid rgba(63,185,80,.35)}
.badge.warn{background:rgba(210,153,34,.14);color:#e3b341;border:1px solid rgba(210,153,34,.4)}
.checks{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:6px 14px;margin-bottom:8px}
.checks table{font-size:13px}
.checks td{padding:7px 6px}
.check-pass{color:#56d364;font-weight:700;font-size:11px;letter-spacing:.06em}
.check-fail{color:#ff7b72;font-weight:700;font-size:11px;letter-spacing:.06em}
.check-sev{font-family:ui-monospace,Consolas,monospace;font-size:11px;color:var(--muted)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.card .k{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}
.card .v{font-size:24px;font-weight:650;margin-top:6px;font-variant-numeric:tabular-nums}
.card .v small{font-size:12px;color:var(--muted);font-weight:400;margin-left:3px}
.meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:8px 22px;
background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:16px 18px}
.meta div{font-size:13px;color:var(--muted);overflow-wrap:anywhere}
.meta b{color:var(--text);font-weight:600}
.crash{background:var(--panel);border:1px solid var(--line);border-left:
5px solid var(--bad);border-radius:10px;padding:14px 16px;margin-bottom:12px}
.crash .top{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.crash .kind{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;
padding:3px 8px;border-radius:5px;color:#0d1117}
.crash .msg{font-weight:600;margin:8px 0 2px;overflow-wrap:anywhere}
.crash .sig{font-family:ui-monospace,Consolas,monospace;font-size:12px;color:var(--muted);
overflow-wrap:anywhere}
.crash pre{background:#0b0f14;border:1px solid var(--line);border-radius:8px;padding:10px 12px;
overflow:auto;font-size:12px;color:#c9d1d9;max-height:260px;margin:10px 0 0}
.shot{max-width:120px;max-height:220px;border:1px solid var(--line);border-radius:6px;display:block}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:var(--muted);font-weight:600;font-size:11px;text-transform:uppercase;
letter-spacing:.06em;border-bottom:1px solid var(--line);padding:8px 6px}
td{border-bottom:1px solid #1a2029;padding:6px;vertical-align:middle;font-variant-numeric:tabular-nums}
tr.new-screen td{background:rgba(88,166,255,.06)}
tr.crash-row td{background:rgba(248,81,73,.07)}
td.mono,.mono{font-family:ui-monospace,Consolas,monospace;font-size:12px;color:#c9d1d9}
tbody tr:hover td{background:#1b2431}
.charts{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:820px){.charts{grid-template-columns:1fr}}
.chart{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.chart .t{font-size:12px;color:var(--muted);margin-bottom:6px}
footer{margin-top:40px;padding-top:16px;border-top:1px solid var(--line);color:var(--muted);font-size:12px}
.empty{color:var(--muted);font-style:italic;padding:8px 2px}
"""


def _esc(value: Any) -> str:
    return escape("" if value is None else str(value), quote=True)


def _as_dict(result: Any) -> Dict[str, Any]:
    if isinstance(result, dict):
        return result
    if hasattr(result, "to_dict"):
        return result.to_dict()
    raise TypeError("expected a session dict or SessionResult")


def _num(value: Optional[float], suffix: str = "", digits: int = 0) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float) and digits:
        return f"{value:.{digits}f}{suffix}"
    if isinstance(value, float):
        return f"{value:.0f}{suffix}"
    return f"{value}{suffix}"


def _human_kb(value: Optional[int]) -> str:
    if not value:
        return "n/a"
    return f"{value / 1024:.0f} MB"


def _embed_image(path: str) -> Optional[str]:
    try:
        if os.path.getsize(path) > MAX_EMBED_BYTES:
            return None
        with open(path, "rb") as handle:
            return base64.b64encode(handle.read()).decode("ascii")
    except OSError:
        return None


def _img(rel: str, out_dir: str, alt: str, embeds: List[str], css: str = "shot") -> str:
    if not rel:
        return ""
    path = os.path.join(out_dir, rel.replace("/", os.sep))
    if len(embeds) < MAX_EMBEDS:
        data = _embed_image(path)
        if data:
            embeds.append(rel)
            return f'<img class="{css}" alt="{_esc(alt)}" src="data:image/png;base64,{data}">'
    if os.path.exists(path):
        return f'<a href="{_esc(rel)}"><img class="{css}" alt="{_esc(alt)}" src="{_esc(rel)}"></a>'
    return ""


def _svg_chart(values: Sequence[Tuple[float, float]], color: str, unit: str = "", height: int = 120) -> str:
    """Tiny dependency-free line chart: ``values`` are (x, y) pairs."""
    width = 520
    if len(values) < 2:
        return '<div class="empty">not enough samples</div>'
    xs = [v[0] for v in values]
    ys = [v[1] for v in values]
    x_min, x_max = min(xs), max(xs)
    y_min, y_max = min(ys), max(ys)
    if x_max == x_min:
        x_max = x_min + 1
    pad_y = (y_max - y_min) * 0.12 or 1.0
    y_lo = y_min - pad_y
    y_hi = y_max + pad_y
    span_y = (y_hi - y_lo) or 1.0

    def sx(value: float) -> float:
        return 8 + (value - x_min) / (x_max - x_min) * (width - 16)

    def sy(value: float) -> float:
        return height - 8 - (value - y_lo) / span_y * (height - 16)

    points = " ".join(f"{sx(x):.1f},{sy(y):.1f}" for x, y in values)
    area = f"8,{height - 8} " + points + f" {width - 8},{height - 8}"
    ticks = "".join(
        f'<text x="0" y="{sy(value) + 3:.0f}" fill="#8b949e" font-size="9">{value:.0f}</text>'
        for value in (y_min, (y_min + y_max) / 2, y_max)
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" width="100%" height="{height}">'
        f'<polygon points="{area}" fill="{color}" opacity="0.10"/>'
        f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="1.8" '
        f'stroke-linejoin="round" stroke-linecap="round"/>'
        f'{ticks}'
        f'<text x="{width - 8}" y="10" fill="#8b949e" font-size="9" text-anchor="end">max '
        f'{y_max:.0f}{unit}</text></svg>'
    )


def _card(label: str, value: str, unit: str = "") -> str:
    suffix = f"<small>{_esc(unit)}</small>" if unit else ""
    return f'<div class="card"><div class="k">{_esc(label)}</div><div class="v">{value}{suffix}</div></div>'


def render_html(result: Any, out_dir: str = "") -> str:
    from .checklist import exploration_coverage

    data = _as_dict(result)
    summary: Dict[str, Any] = data.get("summary", {}) or {}
    meta: Dict[str, Any] = data.get("meta", {}) or {}
    config: Dict[str, Any] = data.get("config", {}) or {}
    crashes: List[Dict[str, Any]] = data.get("crashes", []) or []
    timeline: List[Dict[str, Any]] = data.get("timeline", []) or []
    apk = meta.get("apk", {}) or {}
    embeds: List[str] = []

    checks: List[Dict[str, Any]] = data.get("checks", []) or []
    check_summary = summary.get("check_summary") or {}
    verdict_name = str(check_summary.get("verdict") or "").strip()
    if not verdict_name:
        verdict_name = "fail" if crashes else "pass"
    badge_class = {"fail": "bad", "warn": "warn", "pass": "good"}.get(verdict_name, "good")
    badge_text = {
        "fail": "checks failed" if checks else "crashes found",
        "warn": "warnings",
        "pass": "all checks passed" if checks else "no failures observed",
    }.get(verdict_name, "report")
    steps_run, steps_planned, end_reason = exploration_coverage(data)
    if end_reason != "completed" and (steps_planned or summary.get("end_reason")):
        badge_class = "warn"
        badge_text = f"Results so far · {steps_run} of {steps_planned} steps"
    package = meta.get("package") or config.get("package") or "session"

    cards = "".join(
        [
            _card("Steps run", _num(summary.get("steps_run"))),
            _card("Unique crashes", _num(summary.get("unique_crashes")), "issues"),
            _card("ANRs", _num(summary.get("anr_count"))),
            _card("Screens explored", _num(summary.get("screens_explored"))),
            _card("Avg FPS", _num(summary.get("avg_fps"), digits=1)),
            _card("Min FPS", _num(summary.get("min_fps"), digits=1)),
            _card("Avg jank", _num(summary.get("avg_jank_percent"), "%", 2)),
            _card("Peak memory", _human_kb(summary.get("peak_pss_kb"))),
        ]
    )

    meta_rows = [
        ("Device", f"{meta.get('model') or meta.get('backend', 'n/a')} ({meta.get('serial', 'n/a')})"),
        ("Android", meta.get("android") or "n/a"),
        ("Screen", meta.get("screen") or "n/a"),
        ("Policy", meta.get("policy") or config.get("policy") or "n/a"),
        ("Duration", f"{summary.get('duration_s', 0)} s"),
        ("Started", meta.get("started_at") or "n/a"),
        ("App version", apk.get("version_name") or "n/a"),
        ("Launcher activity", apk.get("launch_activity") or "n/a"),
        ("APK", (apk.get("path") or "n/a")),
        ("SHA-256", (apk.get("sha256") or "n/a")[:32]),
        ("Relaunches", _num(summary.get("relaunches"))),
        ("Tool", meta.get("tool") or f"apkharness {__version__}"),
    ]
    if config.get("gameplay_objective"):
        meta_rows.append(("Gameplay objective", config["gameplay_objective"]))
    meta_html = "".join(f"<div>{_esc(k)}: <b>{_esc(v)}</b></div>" for k, v in meta_rows)

    checks_section = ""
    if checks:
        rows: List[str] = []
        for check in checks:
            passed = bool(check.get("passed"))
            severity = str(check.get("severity", "blocker"))
            mark = "PASS" if passed else ("FAIL" if severity == "blocker" else "WARN")
            css = "check-pass" if passed else "check-fail"
            detail = _esc(check.get("detail", ""))
            rows.append(
                f'<tr><td><span class="{css}">{mark}</span></td>'
                f'<td>{_esc(check.get("title") or check.get("id"))}</td>'
                f'<td class="mono">{_esc(check.get("expected", ""))}</td>'
                f'<td class="mono">{_esc(check.get("actual", ""))}</td>'
                f'<td class="check-sev">{_esc(severity)}</td>'
                f'<td class="mono" style="color:#8b949e;font-size:11px">{detail}</td></tr>'
            )
        checks_section = (
            f'<h2>Checks ({len(checks)})</h2><div class="checks"><table>'
            "<thead><tr><th></th><th>Rule</th><th>Expected</th><th>Actual</th><th>Severity</th>"
            "<th>Detail</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
        )

    crash_html: List[str] = []
    for index, crash in enumerate(crashes, 1):
        color = KIND_COLORS.get(crash.get("kind", ""), "#6b7280")
        label = crash.get("kind", "crash").replace("_", " ").title()
        stack = crash.get("stack") or []
        stack_html = f"<pre>{_esc(chr(10).join(stack))}</pre>" if stack else ""
        shot = _img(crash.get("screenshot", ""), out_dir, f"crash {index}", embeds)
        count = crash.get("count", 1)
        count_html = f'<span class="mono">{count}x</span>' if isinstance(count, int) and count > 1 else ""
        crash_html.append(
            f'<div class="crash"><div class="top">'
            f'<span class="kind" style="background:{color}">{_esc(label)}</span>'
            f'<span class="mono">step {_esc(crash.get("step", "?"))}</span>'
            f'<span class="mono">{_esc(crash.get("ts", ""))}</span>'
            f"{count_html}"
            f'</div><div class="msg">{_esc(crash.get("message", ""))}</div>'
            f'<div class="sig">{_esc(crash.get("signature", ""))}</div>'
            f"{shot}{stack_html}</div>"
        )
    crashes_section = "".join(crash_html) if crash_html else '<div class="empty">No crash, ANR or process death detected in this session.</div>'

    fps_points = [
        (step.get("step", 0), step.get("fps"))
        for step in timeline
        if isinstance(step.get("fps"), (int, float))
    ]
    pss_points = [
        (step.get("step", 0), step.get("pss_kb") / 1024)
        for step in timeline
        if isinstance(step.get("pss_kb"), (int, float))
    ]
    chart_html = (
        '<div class="charts">'
        f'<div class="chart"><div class="t">Frame rate estimate (fps per sample)</div>'
        f'{_svg_chart(fps_points, "#58a6ff")}</div>'
        f'<div class="chart"><div class="t">Total PSS (MB)</div>{_svg_chart(pss_points, "#3fb950", " MB")}</div>'
        "</div>"
    )

    rows: List[str] = []
    flagged = {c.get("step") for c in crashes}
    limit = 400
    for entry in timeline[:limit]:
        step_no = entry.get("step")
        classes = []
        if entry.get("new"):
            classes.append("new-screen")
        if step_no in flagged:
            classes.append("crash-row")
        shot = _img(entry.get("shot", ""), out_dir, f"step {step_no}", embeds, css="shot")
        rows.append(
            f'<tr class="{" ".join(classes)}"><td>{_esc(step_no)}</td>'
            f'<td>{_esc(entry.get("time", ""))}s</td>'
            f'<td class="mono">{_esc(entry.get("action", ""))}</td>'
            f'<td class="mono">{_esc((entry.get("screen") or "")[:8])}</td>'
            f'<td>{"new" if entry.get("new") else ""}</td>'
            f'<td>{"up" if entry.get("alive") else "dead"}</td>'
            f'<td>{shot}</td></tr>'
        )
    table_html = (
        "<table><thead><tr><th>Step</th><th>Time</th><th>Action</th><th>Screen</th><th>New</th>"
        "<th>App</th><th>Screenshot</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
    )
    if len(timeline) > limit:
        table_html += f'<div class="empty">showing first {limit} of {len(timeline)} steps (full data in session.json)</div>'

    llm = summary.get("llm") or {}
    llm_html = ""
    if llm:
        llm_html = (
            f'<div class="meta"><div>LLM model: <b>{_esc(llm.get("model"))}</b></div>'
            f'<div>API calls: <b>{_esc(llm.get("calls"))}</b></div>'
            f'<div>Fallbacks: <b>{_esc(llm.get("failures"))}</b></div>'
            f'<div>Median latency: <b>{_esc(llm.get("median_latency_ms"))} ms</b></div>'
            f'<div>Vision: <b>{"on" if llm.get("vision") else "off"}</b></div></div>'
        )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>apkharness report - {_esc(package)}</title>
<style>{CSS}</style></head><body><div class="wrap">
<header><h1>apkharness session report<small>{_esc(package)} &middot; {_esc(meta.get("policy", config.get("policy", "")))} policy &middot; {_esc(meta.get("started_at", ""))}</small></h1>
<span class="badge {badge_class}">{_esc(badge_text)}</span></header>
<div class="cards">{cards}</div>
<h2>Session</h2><div class="meta">{meta_html}</div>
{llm_html}
{checks_section}
<h2>Crashes &amp; ANRs ({len(crashes)})</h2>{crashes_section}
<h2>Performance</h2>{chart_html}
<h2>Input timeline</h2>{table_html}
<footer>Generated by apkharness {__version__} &middot; artifacts: session.json, logcat.txt, junit.xml, screenshots/</footer>
</div></body></html>
"""


def write_html(result: Any, out_dir: str) -> str:
    data = _as_dict(result)
    html = render_html(data, out_dir)
    path = os.path.join(out_dir, "report.html")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(html)
    return path


def render_junit(result: Any) -> str:
    from .checklist import exploration_coverage

    data = _as_dict(result)
    summary = data.get("summary", {}) or {}
    crashes: List[Dict[str, Any]] = data.get("crashes", []) or []
    meta = data.get("meta", {}) or {}
    package = xml_escape(str(meta.get("package") or "session"))
    duration = summary.get("duration_s", 0) or 0

    checks: List[Dict[str, Any]] = data.get("checks", []) or []
    cases: List[str] = []
    steps_run, steps_planned, end_reason = exploration_coverage(data)
    incomplete = end_reason != "completed" and bool(steps_planned or summary.get("end_reason"))
    skip = f'<skipped message="Results so far: {steps_run} of {steps_planned} planned steps"/>' if incomplete else ""
    cases.append(
        f'  <testcase classname="apkharness.session" name="session_completed" '
        f'time="{float(duration):.3f}">{skip}'
        f'<system-out>{xml_escape("steps=%s screens=%s avg_fps=%s" % (summary.get("steps_run"), summary.get("screens_explored"), summary.get("avg_fps")))}</system-out>'
        f"</testcase>"
    )
    if checks:
        for check in checks:
            check_id = xml_escape(str(check.get("id", "check")))
            severity = str(check.get("severity", "blocker"))
            body = xml_escape(
                f"{check.get('title', '')}\nexpected: {check.get('expected', '')}\n"
                f"actual: {check.get('actual', '')}\n{check.get('detail', '')}"
            )
            if check.get("passed"):
                cases.append(
                    f'  <testcase classname="apkharness.check" name="{check_id}" time="0">'
                    f"<system-out>{body}</system-out></testcase>"
                )
            elif severity == "blocker":
                cases.append(
                    f'  <testcase classname="apkharness.check" name="{check_id}" time="0">'
                    f'<failure message="{xml_escape(str(check.get("title", ""))[:200])}" '
                    f'type="blocker">{body}</failure></testcase>'
                )
            else:
                cases.append(
                    f'  <testcase classname="apkharness.check" name="{check_id}" time="0">'
                    f'<system-out>WARNING (non-blocking): {body}</system-out></testcase>'
                )
    else:
        for crash in crashes:
            kind = xml_escape(str(crash.get("kind", "crash")))
            name = xml_escape(str(crash.get("message", ""))[:140])
            body = xml_escape("\n".join([str(crash.get("message", ""))] + list(crash.get("stack") or [])))
            cases.append(
                f'  <testcase classname="apkharness.{kind}" name="{name}" time="0">'
                f'<failure message="{xml_escape(str(crash.get("message", ""))[:300])}" type="{kind}">{body}</failure>'
                f"</testcase>"
            )

    failure_count = (
        sum(1 for check in checks if not check.get("passed") and check.get("severity") == "blocker")
        if checks
        else len(crashes)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<testsuite name="{package}" tests="{len(cases)}" failures="{failure_count}" errors="0" '
        f'skipped="{int(incomplete)}" time="{float(duration):.3f}" timestamp="{xml_escape(str(meta.get("started_at", "")))}">\n'
        f'  <properties><property name="tool" value="apkharness {__version__}"/>'
        f'<property name="policy" value="{xml_escape(str(meta.get("policy", "")))}"/>'
        f'<property name="device" value="{xml_escape(str(meta.get("serial", "")))}"/></properties>\n'
        + "\n".join(cases)
        + "\n</testsuite>\n"
    )


def write_junit(result: Any, path: str) -> str:
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(render_junit(result))
    return path


def load_session(path: str) -> Dict[str, Any]:
    """Load ``session.json`` (from a run directory or a direct file path)."""
    if os.path.isdir(path):
        path = os.path.join(path, "session.json")
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)
