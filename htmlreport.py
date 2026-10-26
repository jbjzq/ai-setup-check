"""The designed report: an HTML page with charts and cards, printed to PDF by a Chromium browser already on the
machine (Chrome, Edge, Brave, Chromium). Without one, score.py falls back to the plain pdfreport writer.

The raw probe JSON is printed on the last pages, so an AI reading the PDF has the data, and a compressed copy is
appended after the PDF's end marker for read_embedded_json(): PDF readers ignore bytes after %%EOF.
"""
import base64
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import zlib

import brand

THEME_WHY = {
    "Direct agents fast": "Spend your time directing agents, not typing or waiting: voice input, isolated workspaces, and several agents running at once.",
    "Work in a structured way": "Agents finish bigger tasks when the work is specified, planned with dependencies, and delegated in parallel.",
    "Keep context and quality": "Agents stay sharp and safe when they remember the project, start fresh before their context bloats, and get checked by something other than themselves.",
    "Reach everything": "Agents finish tasks end to end when they can use your browser, your desktop apps, your conversations, and a machine that keeps running without you.",
}
THEMES = [("Direct agents fast", ["G1", "G2", "G3"]),
          ("Work in a structured way", ["G4", "G5", "G6"]),
          ("Keep context and quality", ["G7", "G8", "G9"]),
          ("Reach everything", ["G10", "G11", "G12", "G13"])]
# Scores are an ordered magnitude, so one hue light to dark, never status colors.
SCORE_FILL = {0: "#E8E8EA", 1: "#C4B5FD", 2: "#8B5CF6", 3: "#5719D9"}  # Evaboot purple, light to dark
MARKER = b"%AISETUP-JSON "
MAX_JSON_BYTES = 8 * 1024 * 1024
BROWSERS = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "google-chrome", "chromium", "chromium-browser", "microsoft-edge"]

CSS = """
@page { size: A4; margin: 14mm 13mm; }
:root { --navy: #1A1A2E; --ink: #2D1F4E; --muted: #6B7280; --line: #E8E8EA; --track: #EEEEEE;
        --surface: #FFFFFF; --card: #FFFFFF; --brand: #5719D9; --brand-dark: #5420B0; --brand-light: #8B5CF6;
        --lavender: #F3F0FF; --lavender-2: #EDE8FA; --card-brand: #F9F7FF; --ok: #16A34A; --ok-pale: #D1FAE5;
        --sans: "Manrope", -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
        --mono: "JetBrains Mono", ui-monospace, Menlo, monospace; }
* { box-sizing: border-box; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { margin: 0; background: var(--surface); color: var(--ink); font: 10.5px/1.5 var(--sans); }
h1, h2, h3 { color: var(--navy); font-family: var(--sans); }
h1 { font-size: 26px; font-weight: 800; margin: 0; letter-spacing: -0.04em; line-height: 1.1; }
h2 { font-size: 16px; font-weight: 800; margin: 22px 0 10px; letter-spacing: -0.025em; break-after: avoid; }
h3 { font-size: 11.5px; font-weight: 700; margin: 0 0 6px; letter-spacing: -0.01em; }
code { font: 9px var(--mono); background: var(--lavender); color: var(--brand-dark); padding: 0 3px; border-radius: 2px; }
.sub { color: var(--muted); }
.muted { color: var(--muted); }
.brandbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.brandbar img { height: 17px; }
.brandbar span { font: 600 8px var(--mono); letter-spacing: 0.1em; text-transform: uppercase; color: var(--muted); }
header { display: flex; gap: 22px; align-items: center; padding: 20px 22px; border: 1px solid var(--line); border-radius: 6px;
         background: radial-gradient(circle at 85% 0%, rgba(108,43,217,.14), transparent 55%), linear-gradient(180deg, var(--lavender), #fff); }
header .meta { flex: 1; }
header .meta p { margin: 8px 0 0; font-size: 11px; color: var(--ink); }
.eyebrow { font: 600 8.5px var(--mono); letter-spacing: 0.1em; text-transform: uppercase; color: var(--brand); }
.eyebrow::before { content: "\\25A0  "; }
.ring { position: relative; width: 104px; height: 104px; flex: none; }
.ring .num { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; }
.ring .num b { font-size: 27px; font-weight: 800; letter-spacing: -0.04em; color: var(--navy); }
.ring .num span { font: 600 7.5px var(--mono); letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); }
.goal { margin-top: 9px; }
.goal .row { display: flex; align-items: center; gap: 8px; }
.goal .name { flex: 1; font-weight: 600; color: var(--navy); }
.goal .val { width: 28px; text-align: right; font: 600 9.5px var(--mono); color: var(--brand); }
.bar { display: flex; gap: 2px; width: 96px; }
.bar i { flex: 1; height: 8px; border-radius: 2px; background: var(--track); }
.tiles { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; break-inside: avoid; }
.tile { background: var(--card-brand); border: 1px solid var(--line); border-radius: 6px; padding: 10px 12px; }
.tile b { display: block; font-size: 20px; font-weight: 800; letter-spacing: -0.03em; color: var(--navy); }
.tile span { font: 600 7.5px var(--mono); letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); }
.card { background: var(--card); border: 1px solid var(--line); border-radius: 6px; padding: 13px 15px;
        margin-bottom: 9px; break-inside: avoid; display: flex; gap: 12px; box-shadow: 0 4px 16px #6C2BD90F; }
.badge { flex: none; width: 24px; height: 24px; border-radius: 4px; background: var(--brand); color: #fff;
         font: 700 11px var(--mono); display: flex; align-items: center; justify-content: center; }
.card .body { flex: 1; }
.field { display: flex; gap: 8px; margin-top: 5px; }
.chip { flex: none; width: 78px; font: 700 7.5px var(--mono); text-transform: uppercase; letter-spacing: 0.08em;
        padding: 3px 6px; border-radius: 2px; text-align: center; height: fit-content; margin-top: 1px; }
.chip.why { background: var(--lavender-2); color: var(--ink); }
.chip.impact { background: var(--lavender); color: var(--brand); }
.chip.how { background: var(--ok-pale); color: var(--ok); }
.wins { background: var(--card); border: 1px solid var(--line); border-radius: 6px; padding: 8px 15px; break-inside: avoid; }
.wins div { display: flex; gap: 9px; padding: 6px 0; border-bottom: 1px solid var(--line); }
.wins div:last-child { border-bottom: 0; }
.wins div::before { content: ""; flex: none; width: 10px; height: 10px; margin-top: 3px; border: 1.5px solid var(--brand); border-radius: 2px; }
table { width: 100%; border-collapse: collapse; background: var(--card); border: 1px solid var(--line); }
th, td { padding: 5px 9px; text-align: left; border-bottom: 1px solid var(--line); vertical-align: middle; }
th { font: 600 7.5px var(--mono); text-transform: uppercase; letter-spacing: 0.1em; color: var(--muted); background: var(--card-brand); }
td.num, th.num { text-align: right; white-space: nowrap; }
.cell { display: inline-block; min-width: 24px; padding: 1px 0; border-radius: 2px; text-align: center; font: 600 9px var(--mono); }
.legend { display: flex; flex-wrap: wrap; gap: 6px 12px; align-items: center; margin: 4px 0 10px; font: 500 8px var(--mono); color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
.legend i { display: inline-block; width: 14px; height: 8px; border-radius: 2px; margin-right: 4px; vertical-align: middle; }
.scan { display: grid; grid-template-columns: 1fr 1fr; gap: 2px 28px; break-inside: avoid; }
.scan .goal { margin-top: 4px; }
.guide { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.theme { background: var(--card); border: 1px solid var(--line); border-radius: 6px; padding: 12px 14px; break-inside: avoid; }
.guide .theme p { margin: 4px 0 0; font-size: 9.5px; color: var(--ink); }
.page-break { break-before: page; }
.theme-block { margin-top: 18px; }
.theme-block + .theme-block { break-before: page; margin-top: 0; }
.theme-head { display: flex; justify-content: space-between; align-items: flex-end; gap: 20px; padding: 16px 18px;
              background: radial-gradient(circle at 90% 0%, rgba(108,43,217,.16), transparent 60%), var(--lavender);
              border-radius: 6px; break-after: avoid; }
.theme-head h2 { margin: 4px 0 3px; font-size: 18px; }
.theme-head p { margin: 0; font-size: 10px; max-width: 470px; color: var(--ink); }
.theme-score { text-align: right; flex: none; width: 110px; }
.theme-score b { font-size: 26px; font-weight: 800; color: var(--brand); letter-spacing: -0.04em; }
.theme-score span { font: 600 11px var(--mono); color: var(--muted); }
.meter { height: 5px; background: #fff; border-radius: 2px; margin-top: 4px; overflow: hidden; }
.meter i { display: block; height: 100%; background: var(--brand); }
.goal-block { border: 1px solid var(--line); border-radius: 6px; padding: 12px 14px; margin-top: 8px; break-inside: avoid; }
.goal-head { display: flex; align-items: center; gap: 10px; }
.goal-head h3 { flex: 1; margin: 0; font-size: 13px; }
.gid { flex: none; font: 700 8px var(--mono); color: #fff; background: var(--brand); border-radius: 2px; padding: 3px 6px; letter-spacing: 0.05em; }
.goal-block .why { margin: 4px 0 8px; font-size: 9.5px; color: var(--muted); }
.pane { border-radius: 4px; padding: 10px 12px; margin-top: 6px; }
.improve { display: grid; grid-template-columns: 1.35fr 1fr; gap: 14px; align-items: center; }
.improve ol { margin: 0; padding-left: 16px; font-size: 10px; }
.improve li { margin-bottom: 4px; }
.improve li::marker { color: var(--brand); font-weight: 700; }
.diagram { margin: 0; background: #fff; border: 1px solid var(--lavender-2); border-radius: 4px; padding: 8px; }
.diagram figcaption { font-size: 8.5px; color: var(--muted); margin-top: 4px; text-align: center; }
.pane p { margin: 0 0 4px; font-size: 10px; }
.pane.next { background: var(--card-brand); border: 1px solid var(--lavender-2); }
.pane.now { background: #FAFAFA; border: 1px solid var(--line); }
.pane-label { font: 700 7.5px var(--mono); text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 5px; color: var(--muted); }
.pane-label::before { content: "\\25CF  "; }
.pane.next .pane-label { color: var(--brand); }
.pane .impact { color: var(--ink); font-size: 9.5px; }
pre { white-space: pre-wrap; word-break: break-all; font: 6.5px/1.35 var(--mono); color: var(--ink);
      background: var(--card-brand); border: 1px solid var(--line); border-radius: 4px; padding: 10px; }
footer { margin-top: 18px; font: 500 8px var(--mono); color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; }
.download { display: inline-block; background: var(--brand); color: #fff; text-decoration: none; padding: 7px 12px;
            border-radius: 4px; font: 600 11px var(--sans); }
@media screen {
  body { max-width: 880px; margin: 0 auto; padding: 28px 16px 48px; font-size: 13px; }
  .page-break, .theme-block + .theme-block { break-before: auto; margin-top: 28px; }
  .improve ol, .pane p, .pane .impact { font-size: 12.5px; }
}
.improve > *, .meta, .pane, .goal-head h3 { min-width: 0; }
p, li, td, .pane, h1, h2, h3 { overflow-wrap: anywhere; }
code { overflow-wrap: anywhere; word-break: break-word; }
@media screen and (max-width: 640px) {
  header, .theme-head { flex-direction: column; align-items: flex-start; }
  .theme-score { text-align: left; }
  .improve { grid-template-columns: 1fr; }
  .tiles { grid-template-columns: 1fr 1fr; }
  .scan, .guide { grid-template-columns: 1fr; }
  .field { flex-direction: column; gap: 3px; }
}
@media print { .download { display: none; } }
"""


def font_faces():
    return ('@font-face { font-family: "Manrope"; font-weight: 200 800; '
            f'src: url(data:font/woff2;base64,{brand.MANROPE_WOFF2}) format("woff2"); }}'
            '@font-face { font-family: "JetBrains Mono"; font-weight: 100 800; '
            f'src: url(data:font/woff2;base64,{brand.MONO_WOFF2}) format("woff2"); }}')


def inline(text):
    """Escape, then keep `code` and **bold** from the AI's text."""
    t = html.escape(str(text))
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    return re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", t)


def bar(score):
    return '<div class="bar">' + "".join(
        f'<i style="background:{SCORE_FILL[score] if k < score else "var(--track)"}"></i>' for k in range(3)) + "</div>"


def ring(value, total, label):
    r, c = 44, 2 * 3.14159 * 44
    frac = value / total if total else 0
    return (f'<div class="ring"><svg width="104" height="104" viewBox="0 0 104 104">'
            f'<circle cx="52" cy="52" r="{r}" fill="none" stroke="#EDE8FA" stroke-width="9"/>'
            f'<circle cx="52" cy="52" r="{r}" fill="none" stroke="#5719D9" stroke-width="9" stroke-linecap="butt" '
            f'stroke-dasharray="{c * frac:.1f} {c:.1f}" transform="rotate(-90 52 52)"/></svg>'
            f'<div class="num"><b>{value}<span style="font-size:13px;color:var(--muted)">/{total}</span></b>'
            f'<span>{html.escape(label)}</span></div></div>')


def legend():
    names = {0: "not served", 1: "partly", 2: "served, with gaps", 3: "routine"}
    return '<div class="legend">' + "".join(
        f'<span><i style="background:{SCORE_FILL[s]}"></i>{s} {names[s]}</span>' for s in range(4)) + "</div>"


def goal_sections_html(review, sections):
    """One full-width section per theme, one block per goal: score, current stack, and a way to improve."""
    by_id = {g["id"]: g for g in review["goals"]}
    titles = {gid: title for gid, title, _ in sections}
    fields = {gid: f for gid, _, f in sections}
    out = []
    for n, (theme, ids) in enumerate(THEMES, 1):
        got, top = sum(by_id[i]["score"] for i in ids), 3 * len(ids)
        out.append(f'<section class="theme-block"><div class="theme-head"><div><div class="eyebrow">Category {n}</div>'
                   f'<h2>{theme}</h2><p class="sub">{THEME_WHY[theme]}</p></div>'
                   f'<div class="theme-score"><b>{got}</b><span>/{top}</span>{meter(got, top)}</div></div>')
        for i in ids:
            g, f = by_id[i], fields.get(i, {})
            imp = g.get("improve") if isinstance(g.get("improve"), dict) else {"steps": [g["improve"]] if g.get("improve") else []}
            steps = imp.get("steps") or [f.get("First step", "")]
            result = imp.get("result") or f.get("Impact", "")
            why = f.get("Why", "")
            out.append(f'<div class="goal-block"><div class="goal-head"><span class="gid">{i}</span>'
                       f'<h3>{html.escape(titles.get(i, ""))}</h3>{bar(g["score"])}<span class="val">{g["score"]}/3</span></div>'
                       f'<p class="why">{inline(why[:1].upper() + why[1:])}</p>'
                       f'<div class="pane next"><div class="pane-label">A way to improve</div><div class="improve">'
                       f'<div><ol>{"".join(f"<li>{inline(x)}</li>" for x in steps)}</ol>'
                       + (f'<p class="impact"><strong>What it changes:</strong> {inline(result)}</p>' if result else "")
                       + f'</div>{diagram(i)}</div></div>'
                       f'<div class="pane now"><div class="pane-label">Your current stack</div>'
                       f'<p><strong>{inline(g["tools"]) or "Nothing yet"}</strong> · {inline(g["evidence"])}</p></div></div>')
        out.append("</section>")
    return "".join(out)


# One concept diagram per goal: columns of boxes left to right ("\n" breaks a label), each column joined to the
# next. Columns of equal size connect one to one; otherwise every box connects to every box of the next column.
DIAGRAMS = {
    "G1": ([["You speak"], ["Dictation\napp"], ["Text where\nthe cursor is"], ["Agent"]],
           "Speaking is about three times faster than typing, in any app or terminal."),
    "G2": ([["One repo"], ["Copy A", "Copy B", "Copy C"], ["Agent A", "Agent B", "Agent C"]],
           "Each task gets its own working copy and branch, so agents never edit the same files."),
    "G3": ([["You"], ["Agent 1", "Agent 2", "Agent 3", "Agent 4"], ["Result", "Result", "Result", "Result"]],
           "You direct; several agents work at the same time."),
    "G4": ([["Idea"], ["Spec"], ["Plan"], ["Build"], ["Review"]],
           "Write down what to build, then how, before any code is written."),
    "G5": ([["Task A", "Task B"], ["Task C"], ["Task D", "Task E"]],
           "A and B run together; C waits for both; D and E start when C is done."),
    "G6": ([["Main\nagent"], ["Research", "Write code", "Review"], ["Short\nsummary"]],
           "Sub-tasks run in parallel and only a summary comes back, so the main context stays small."),
    "G7": ([["Global rules", "Repo rules", "Memory", "Docs"], ["Every new\nsession"]],
           "Each session starts already knowing the rules, the project and past lessons."),
    "G8": ([["Session 1\ncontext 50%"], ["Handoff\nnote"], ["Session 2\nfresh"]],
           "Before the context window fills, save the state and continue in a fresh session."),
    "G9": ([["Agent's\nchange"], ["Tests", "Second model", "Blocking hooks"], ["Merge"]],
           "Nothing merges until something other than the author has checked it."),
    "G10": ([["Agent"], ["Your browser", "Headless browser"], ["Logged-in tools", "UI tests"]],
            "Your own profile for work behind logins, a headless one for testing."),
    "G11": ([["Agent"], ["Reads the\nscreen"], ["Clicks and\ntypes"], ["Native app\nor dialog"]],
            "The agent finishes steps in apps instead of handing them back to you."),
    "G12": ([["Slack", "Email", "WhatsApp"], ["Agent"], ["Draft\nreply"], ["You\napprove"]],
            "The agent reads the thread behind a task and drafts the answer; you approve sending."),
    "G13": ([["Schedule\nor event"], ["Remote\nmachine"], ["Agents\nwork"], ["Your\nphone"]],
            "Work continues while your laptop is closed, and agents reach you when they need you."),
}


def diagram(gid):
    """Small left-to-right SVG flow for one goal, from DIAGRAMS."""
    if gid not in DIAGRAMS:
        return ""
    cols, caption = DIAGRAMS[gid]
    W, H, gap, vgap = 300, 128, 16, 6
    bw = (W - gap * (len(cols) - 1)) / len(cols)
    pos = []
    for i, col in enumerate(cols):
        bh = min(30, (H - vgap * (len(col) - 1)) / len(col))
        top = (H - len(col) * bh - vgap * (len(col) - 1)) / 2
        pos.append([(i * (bw + gap), top + j * (bh + vgap), bh, label.split("\n")) for j, label in enumerate(col)])
    svg = [f'<svg viewBox="-2 -2 {W + 4} {H + 4}" width="100%" role="img" aria-label="{html.escape(caption)}">',
           '<defs><marker id="a" viewBox="0 0 6 6" refX="5" refY="3" markerWidth="5" markerHeight="5" orient="auto">'
           '<path d="M0,0 L6,3 L0,6 z" fill="#8B5CF6"/></marker></defs>']
    for left, right in zip(pos, pos[1:]):
        pairs = zip(left, right) if len(left) == len(right) else [(a, b) for a in left for b in right]
        for (x1, y1, h1, _), (x2, y2, h2, _) in pairs:
            svg.append(f'<line x1="{x1 + bw:.1f}" y1="{y1 + h1 / 2:.1f}" x2="{x2 - 2:.1f}" y2="{y2 + h2 / 2:.1f}" '
                       'stroke="#8B5CF6" stroke-width="1" stroke-dasharray="2 2" marker-end="url(#a)"/>')
    for i, col in enumerate(pos):
        fill, stroke, ink = ("#5719D9", "#5719D9", "#FFFFFF") if i == len(pos) - 1 else ("#F9F7FF", "#C4B5FD", "#1A1A2E")
        for x, y, h, lines in col:
            svg.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{h:.1f}" rx="3" fill="{fill}" stroke="{stroke}"/>')
            for k, line in enumerate(lines):
                ty = y + h / 2 + (k - (len(lines) - 1) / 2) * 9 + 3
                svg.append(f'<text x="{x + bw / 2:.1f}" y="{ty:.1f}" text-anchor="middle" font-size="8" font-family="Manrope, sans-serif" font-weight="600" fill="{ink}">'
                           f'{html.escape(line)}</text>')
    svg.append("</svg>")
    return f'<figure class="diagram">{"".join(svg)}<figcaption>{html.escape(caption)}</figcaption></figure>'


def meter(value, total):
    pct = 100 * value / total if total else 0
    return f'<div class="meter"><i style="width:{pct:.0f}%"></i></div>'


def improvement_cards(review):
    out = []
    for n, i in enumerate(review["improvements"], 1):
        fields = "".join(f'<div class="field"><span class="chip {cls}">{label}</span><div>{inline(i[key])}</div></div>'
                         for cls, label, key in (("why", "Why", "why"), ("impact", "Impact", "impact"),
                                                 ("how", "How to start", "how")))
        out.append(f'<div class="card"><div class="badge">{n}</div><div class="body"><h3>{inline(i["title"])}</h3>'
                   f'{fields}</div></div>')
    return "".join(out)


def tiles(items):
    return '<div class="tiles">' + "".join(
        f'<div class="tile"><b>{html.escape(v)}</b><span>{html.escape(k)}</span></div>' for k, v in items) + "</div>"


def guide_cards(sections):
    out = ['<div class="guide">']
    for gid, title, f in sections:
        out.append(f'<div class="theme"><h3>{gid} · {html.escape(title)}</h3>'
                   + "".join(f'<p><strong>{k}:</strong> {inline(f[k])}</p>' for k in ("Why", "Impact", "First step") if k in f)
                   + "</div>")
    return "".join(out) + "</div>"


def scan_solo(rows):
    return '<div class="scan">' + "".join(
        f'<div class="goal"><div class="row"><span class="name" style="font-weight:500">{html.escape(label)}</span>'
        f'{bar(scores[0])}<span class="val">{scores[0]}</span></div></div>' for label, scores, _ in rows) + "</div>"


def scan_matrix(rows, names, totals, first="Dimension"):
    head = f"<tr><th>{first}</th>" + "".join(f'<th class="num">{html.escape(n)}</th>' for n in names) + "</tr>"
    body = ""
    for label, scores, _ in rows:
        cells = "".join(
            '<td class="num">' + ("n/a" if s is None else
                                  f'<span class="cell" style="background:{SCORE_FILL[s]};color:{"#fff" if s >= 2 else "var(--ink)"}">{s}</span>')
            + "</td>" for s in scores)
        body += f"<tr><td>{html.escape(label)}</td>{cells}</tr>"
    body += "<tr><td><strong>Total</strong></td>" + "".join(f'<td class="num"><strong>{t}</strong></td>' for t in totals) + "</tr>"
    return f"<table>{head}{body}</table>"


def activity_table(rows, names):
    head = "<tr><th>Metric</th>" + "".join(f'<th class="num">{html.escape(n)}</th>' for n in names) + "</tr>"
    body = "".join(f"<tr><td>{html.escape(label)}</td>" + "".join(f'<td class="num">{html.escape(v)}</td>' for v in vals)
                   + "</tr>" for label, vals in rows)
    return f"<table>{head}{body}</table>"


def build_html(docs, review, sections, scan_rows, scan_totals, activity_rows, solo_tiles, hands_free, pdf_url=None):
    base = docs[0]
    names = [d["name"] for d in docs]
    titles = {gid: title for gid, title, _ in sections}
    window = html.escape(str(base.get("window_days", 30)))
    parts = [f'<div class="brandbar"><img src="data:image/svg+xml;base64,{brand.LOGO_SVG}" alt="Evaboot">'
             + (f'<a class="download" href="{html.escape(pdf_url)}">Download PDF</a>' if pdf_url else
                '<span>Internal · AI setup check</span>') + '</div>']
    if len(docs) == 1:
        if review:
            total = sum(g["score"] for g in review["goals"])
            hero = ring(total, 39, "goal score")
            summary = inline(review["summary"])
        else:
            got = str(scan_totals[0]).split("/")[0]
            hero = ring(int(got), 45, "quick scan") if got.isdigit() else ""
            summary = ("Your scores by goal need Claude Code to write them. Below are a quick scan by tool name "
                       "and a guide to every goal.")
        parts.append(f'<header>{hero}<div class="meta"><div class="eyebrow">AI setup report · last {window} days</div>'
                     f'<h1>{html.escape(base["name"])}</h1><p>{summary}</p></div></header>')
        if review:
            parts += ['<h2>Your setup, goal by goal</h2>', legend(), goal_sections_html(review, sections),
                      '<h2 class="page-break">Your top priorities</h2>', '<p class="sub">Across all four categories, the '
                      'changes with the most impact for you, highest first.</p>', improvement_cards(review)]
            if review["quick_wins"]:
                parts += ["<h2>Quick wins (under 15 minutes)</h2>",
                          '<div class="wins">' + "".join(f"<div><span>{inline(q)}</span></div>" for q in review["quick_wins"]) + "</div>"]
        parts += ["<h2>Activity</h2>", tiles(solo_tiles)]
        if hands_free:
            parts.append(f'<p class="sub" style="margin-top:8px"><strong>Hands-free check:</strong> {html.escape(hands_free[0])}</p>')
        if scan_rows and scan_rows[0][1][0] is not None:
          parts += ['<h2>Quick scan by tool name</h2>',
                  '<p class="sub">Matches known tool names, 0 to 3 per dimension. '
                  + ('The goal scores above judge every tool by what it does, so they are the ones that count.' if review
                     else 'Tools with unusual names can be missed, so read a 0 as "not found", not "absent".')
                  + '</p>', legend(), scan_solo(scan_rows)]
        if not review:
            parts += ["<h2>Ways to improve</h2>", '<p class="sub">Each goal, why it matters, what it changes and a '
                      'first step. Skip the ones your setup already covers.</p>', guide_cards(sections)]
    else:
        parts.append(f'<header><div class="meta"><div class="eyebrow">AI setup comparison · last {window} days</div>'
                     f'<h1>{html.escape(", ".join(names))}</h1><p>Baseline: {html.escape(base["name"])}. Goal scores come from '
                     'each person\'s own report; the quick scan matches tool names only.</p></div></header>')
        if any(d.get("review") for d in docs):
            goal_rows = [(f"{gid} · {title}", [next((g["score"] for g in (d.get("review") or {}).get("goals", [])
                                                     if g["id"] == gid), None) for d in docs], [])
                         for gid, title, _ in sections]
            goal_totals = [f"{sum(g['score'] for g in d['review']['goals'])}/39" if d.get("review") else "n/a" for d in docs]
            parts += ["<h2>Goals</h2>", '<p class="sub">Scored by each person\'s own Claude Code against the goals, '
                      'judging every tool by what it does.</p>', legend(), scan_matrix(goal_rows, names, goal_totals, "Goal")]
        parts += ["<h2>Quick scan by tool name</h2>", legend(), scan_matrix(scan_rows, names, scan_totals),
                  "<h2>Activity</h2>", activity_table(activity_rows, names)]
        if hands_free:
            parts += ["<h2>Hands-free check</h2>"] + [f'<p class="sub">{html.escape(h)}</p>' for h in hands_free]
    raw = "\n".join(json.dumps(d, indent=1, ensure_ascii=False) for d in docs)
    parts += ['<h2 class="page-break">Raw probe data</h2>',
              '<p class="sub">Machine-readable copy of every probe result in this report, for an AI to analyze against '
              'the goals above.</p>', f"<pre>{html.escape(raw)}</pre>",
              f'<footer>Evaboot · AI setup check · github.com/jbjzq/ai-setup-check</footer>']
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>AI setup report</title>'
            f"<style>{font_faces()}{CSS}</style></head><body>{''.join(parts)}</body></html>")


def find_browser():
    for b in BROWSERS:
        path = b if os.path.isabs(b) else shutil.which(b)
        if path and os.path.exists(path):
            return path
    return None


def print_pdf(page, out_path, docs, timeout=90):
    """Print the page to PDF with a local Chromium and append the machine copy. False when no browser could."""
    browser = find_browser()
    if not browser:
        return False
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "report.html")
        with open(src, "w", encoding="utf-8") as f:
            f.write(page)
        target = os.path.join(tmp, "report.pdf")
        # A throwaway profile, so the person's open browser and its profiles are never touched.
        args = [browser, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                f"--user-data-dir={os.path.join(tmp, 'profile')}", "--no-pdf-header-footer",
                "--print-to-pdf-no-header", f"--print-to-pdf={target}", "file://" + src]
        try:
            subprocess.run(args, capture_output=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError):
            return False
        if not os.path.exists(target) or os.path.getsize(target) < 1000:
            return False
        with open(target, "rb") as f:
            data = f.read()
    blob = base64.b64encode(zlib.compress(json.dumps(docs).encode("utf-8"), 9))
    with open(out_path, "wb") as f:
        f.write(data + b"\n" + MARKER + blob + b"\n")
    return True


def read_embedded_json(path):
    with open(path, "rb") as f:
        data = f.read()
    i = data.rfind(MARKER)
    if i < 0:
        return []
    blob = data[i + len(MARKER):].split(b"\n", 1)[0]
    try:
        # Bounded: a tiny compressed blob must not expand into gigabytes (uploads come from anyone).
        decoder = zlib.decompressobj()
        raw = decoder.decompress(base64.b64decode(blob), MAX_JSON_BYTES + 1)
        if len(raw) > MAX_JSON_BYTES or not decoder.eof:
            return []
        return json.loads(raw)
    except (ValueError, zlib.error):
        return []
