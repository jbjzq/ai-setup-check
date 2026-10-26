#!/usr/bin/env python3
"""Score one or more probe.py results against a baseline probe (JB's stack) and print a Markdown report.

Usage: python3 score.py baseline.json [colleague.json|report.pdf ...] [--pdf out.pdf] > report.md
One file scores that setup alone. A PDF input is a report this script wrote: its embedded probe data is read back.
--pdf also writes the report as a PDF with the goals rubric and the raw probe JSON appended.
--dump report.pdf prints the probe JSON embedded in a report.
--coach (one person only) adds a review of what to improve, why and the impact, written by the local
Claude Code against goals.md, or the goals guide when Claude Code is unavailable.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import htmlreport  # noqa: E402
from coach import ai_review, goal_sections, guide_markdown, review_markdown  # noqa: E402
from pdfreport import read_raw_json, write_pdf  # noqa: E402

AI_IDES = {"Cursor", "Windsurf", "Zed", "Kiro", "Void", "Trae"}
WORKSPACE_APPS = {"Superset", "Conductor"}


def score_ide(d):
    ide = d.get("ide", {})
    running = set(ide.get("running", []))
    if running & AI_IDES or WORKSPACE_APPS & set(d.get("agent_apps", [])):
        return 3, ", ".join(sorted(running | (WORKSPACE_APPS & set(d.get("agent_apps", []))))) or "AI IDE"
    if set(ide.get("installed", [])) & AI_IDES:
        return 2, "AI IDE installed, not running: " + ", ".join(ide["installed"])
    if ide.get("installed"):
        return 1, "classic IDE only: " + ", ".join(ide["installed"])
    return 0, "no IDE found"


def score_multi_repo(d):
    m = d.get("multi_repo", {})
    managed = bool(WORKSPACE_APPS & set(m.get("tools", [])) or "superset" in m.get("tools", []))
    wt = m.get("linked_worktrees", 0)
    note = f"{m.get('git_checkouts', 0)} checkouts, {wt} worktrees, tools: {', '.join(m.get('tools', [])) or 'none'}"
    if managed and wt >= 10:
        return 3, note
    if managed or wt >= 3:
        return 2, note
    return (1 if m.get("git_checkouts") else 0), note


def score_parallel(d):
    par = d.get("parallel_all_clients") or {}
    peak, hours = par.get("peak_parallel_sessions", 0), par.get("hours_2plus_parallel", 0)
    note = f"peak {peak} sessions at once, {hours:.0f} h with 2+ working; CLIs: {', '.join(d.get('agent_clis', [])) or 'none'}"
    if peak >= 5 and hours >= 20:
        return 3, note
    if peak >= 3:
        return 2, note
    return (1 if peak >= 2 else 0), note


def score_voice(d):
    voice = d.get("voice", {})
    if voice.get("running"):
        return 3, "running: " + ", ".join(voice["running"])
    if voice.get("apps"):
        return 2, "installed, not running: " + ", ".join(voice["apps"])
    return (1 if voice.get("skills_or_mcp") else 0), ", ".join(voice.get("skills_or_mcp", [])) or "no voice input"


def wf(d, *path):
    cur = d.get("workflow") or {}
    for k in path:
        cur = (cur or {}).get(k)
    return cur


def score_phases(d):
    cc = d.get("claude_code") or {}
    parts, s = [], 0
    for phase in ("spec", "plan", "execute"):
        info = wf(d, "phases", phase) or {}
        used = info.get("calls", 0) > 0
        if phase == "plan":
            used = used or cc.get("plan_mode_exits", 0) > 0
        s += bool(info.get("skills")) and used
        parts.append(f"{phase}: {', '.join(info.get('skills', [])) or 'none'} ({info.get('calls', 0)} calls)")
    return s, "; ".join(parts)


def score_dag(d):
    docs = wf(d, "docs") or {}
    dag_plans, plans = docs.get("plans_with_dependency_graph", 0), docs.get("plans_files", 0)
    note = f"{dag_plans} of {plans} plans declare dependencies; DAG skills: {', '.join(wf(d, 'dag_skills') or []) or 'none'}"
    if wf(d, "dag_skills") and dag_plans >= 5:
        return 3, note
    if dag_plans:
        return 2, note
    return (1 if plans or docs.get("claude_plan_mode_files") else 0), note


def score_subagents(d):
    cc = d.get("claude_code") or {}
    par, wt = cc.get("parallel_agent_dispatches", 0), cc.get("agents_in_worktrees", 0)
    note = (f"{par} messages launching 2+ agents (max {cc.get('max_agents_in_one_message', 0)}), {wt} in worktrees, "
            f"{cc.get('subagent_calls', 0)} subagents total, {wf(d, 'subagent_definitions') or 0} custom agent types")
    if par >= 20 and wt:
        return 3, note
    if par >= 5:
        return 2, note
    return (1 if cc.get("subagent_calls") else 0), note


def score_handoff(d):
    h = wf(d, "handoff") or {}
    docs = wf(d, "docs") or {}
    note = (f"skills: {', '.join(h.get('skills', [])) or 'none'} ({h.get('calls', 0)} calls), "
            f"{docs.get('handoffs_files_in_window', 0)} handoff docs this window, "
            f"automatic: {', '.join(h.get('auto_handoff_skills', [])) or 'none'}")
    if h.get("auto_handoff_skills"):
        return 3, note
    if h.get("calls") or docs.get("handoffs_files_in_window"):
        return 2, note
    return (1 if h.get("skills") else 0), note


def score_context_layers(d):
    c, docs = wf(d, "context") or {}, wf(d, "docs") or {}
    s = (bool(c.get("global_instruction_files"))
         + (docs.get("repos_with_agent_instructions", 0) >= 3 or bool(docs.get("repos_with_docs_documentation")))
         + (c.get("memory_files", 0) >= 10 or bool(c.get("context_skills"))))
    return s, (f"{c.get('global_instruction_files', 0)} global instruction files, "
               f"{docs.get('repos_with_agent_instructions', 0)} repos with AGENTS/CLAUDE.md, "
               f"{docs.get('repos_with_docs_documentation', 0)} with docs/documentation, {c.get('memory_files', 0)} memory files")


def score_context_switching(d):
    c, h = wf(d, "context") or {}, wf(d, "handoff") or {}
    cc = d.get("claude_code") or {}
    manual = (cc.get("compactions") or {}).get("manual", 0)
    s = bool(c.get("statusline_shows_context")) + (bool(c.get("compaction_rules")) or manual > 0) + bool(h.get("auto_handoff_skills"))
    return s, (f"status line shows context: {'yes' if c.get('statusline_shows_context') else 'no'}; "
               f"compaction rules: {'yes' if c.get('compaction_rules') else 'no'}; compactions {cc.get('compactions') or {}}; "
               f"median peak context {cc.get('median_peak_context_tokens', 0) // 1000}k, "
               f"{cc.get('sessions_over_500k_context', 0)} sessions over 500k")


def score_guardrails(d):
    g = wf(d, "guardrails") or {}
    s = (g.get("hook_commands", 0) >= 5) + (bool(g.get("review_skills")) and bool(g.get("tdd_skills"))) \
        + (g.get("scheduled_jobs", 0) > 0 or bool(g.get("automation_skills")))
    return s, (f"{g.get('hook_commands', 0)} hooks on {len(g.get('hook_events', []))} events; review: "
               f"{', '.join(g.get('review_skills', [])) or 'none'}; TDD: {', '.join(g.get('tdd_skills', [])) or 'none'}; "
               f"{g.get('scheduled_jobs', 0)} scheduled jobs")


def _used(d, names):
    calls = (d.get("claude_code") or {}).get("mcp_calls_by_server", {})
    return any(calls.get(n, 0) > 0 for n in names)


def score_browser(d):
    b = d.get("browser", {})
    own, headless = b.get("own_browser", []), b.get("headless", [])
    s = bool(own) + bool(headless) + _used(d, own + headless)
    return s, f"own: {', '.join(own) or 'none'}; headless: {', '.join(headless) or 'none'}"


def score_vm(d):
    v = d.get("vm", {})
    remote = v.get("ssh_hosts", 0) > 0 or v.get("aws_cli_configured")
    note = f"{v.get('ssh_hosts', 0)} ssh hosts, AWS CLI {'yes' if v.get('aws_cli_configured') else 'no'}, " \
           f"apps: {', '.join(v.get('apps', [])) or 'none'}, agent tools: {', '.join(v.get('skills_or_mcp', [])) or 'none'}"
    if remote and v.get("skills_or_mcp"):
        return 3, note
    if remote:
        return 2, note
    return (1 if v.get("apps") else 0), note


def score_desktop(d):
    dc = d.get("desktop_control", {})
    tools = dc.get("mcp_or_skills", [])
    note = ", ".join(tools + dc.get("clis", []) + dc.get("apps", [])) or "none"
    if tools and _used(d, tools):
        return 3, note
    if tools:
        return 2, note
    return (1 if dc.get("clis") or dc.get("apps") else 0), note


def score_comms(d):
    c = d.get("comms", {})
    linked = [k for k in ("whatsapp", "gmail", "slack") if c.get(k, {}).get("clis") or c.get(k, {}).get("mcp_or_skills")]
    return len(linked), "connected: " + (", ".join(linked) or "none")


DIMENSIONS = [
    ("IDE", score_ide),
    ("Multi-repo management", score_multi_repo),
    ("Parallel sessions (Claude + Codex)", score_parallel),
    ("Voice input", score_voice),
    ("Spec, plan, execute phases", score_phases),
    ("Task dependency graph (DAG)", score_dag),
    ("Parallel subagents", score_subagents),
    ("Handoff", score_handoff),
    ("Context layers (instructions, memory, docs)", score_context_layers),
    ("Context switching when bloated", score_context_switching),
    ("Guardrails and automation", score_guardrails),
    ("Browser control (own + headless)", score_browser),
    ("Virtual machine", score_vm),
    ("Desktop control", score_desktop),
    ("WhatsApp, Gmail, Slack CLIs", score_comms),
]

ACTIVITY = [
    ("GitHub PRs merged", ("github", "prs_merged")),
    ("GitHub commits", ("github", "commits")),
    ("GitHub PRs reviewed", ("github", "prs_reviewed")),
    ("Claude Code sessions", ("claude_code", "sessions")),
    ("Claude Code active days", ("claude_code", "active_days")),
    ("Claude Code tokens", ("claude_code", "tokens_total")),
    ("Claude Code output tokens", ("claude_code", "tokens_output")),
    ("Codex tokens", ("codex", "tokens_total")),
]


def get(d, path):
    for k in path:
        d = (d or {}).get(k)
    return d


def human(n):
    if n is None:
        return "n/a"
    for unit, size in (("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if abs(n) >= size:
            return f"{n / size:.1f}{unit}"
    return str(n)


def hands_free(d):
    """Can this person code by voice with agents reaching all their data? Lists what is missing."""
    missing = []
    if not (d.get("voice", {}).get("apps")):
        missing.append("voice dictation")
    if not d.get("browser", {}).get("own_browser"):
        missing.append("agent control of their own browser")
    if not d.get("desktop_control", {}).get("mcp_or_skills"):
        missing.append("agent desktop control")
    for k in ("whatsapp", "gmail", "slack"):
        c = d.get("comms", {}).get(k, {})
        if not (c.get("clis") or c.get("mcp_or_skills")):
            missing.append({"whatsapp": "WhatsApp", "gmail": "Gmail", "slack": "Slack"}[k] + " access")
    return missing


def report(base, people):
    who = f"Baseline: **{base['name']}**." if people else f"Setup of **{base['name']}**."
    out = ["# AI setup report", "",
           f"{who} Window: last {base.get('window_days', 30)} days.", "",
           "## Quick scan", "",
           "Keyword matching on tool names, each dimension 0 to 3. It only spots known tools: the goal-based "
           "evaluation in the section \"AI setup goals\" judges every installed tool by what it is for.", ""]
    cols = [base] + people
    out.append("| Dimension | " + " | ".join(p["name"] for p in cols) + " |")
    out.append("|---|" + "---|" * len(cols))
    totals = [0] * len(cols)
    notes = {p["name"]: [] for p in cols}
    for label, fn in DIMENSIONS:
        row = []
        for i, p in enumerate(cols):
            if "ide" not in p:
                row.append("n/a")
                continue
            s, note = fn(p)
            totals[i] += s
            row.append(str(s))
            notes[p["name"]].append(f"- **{label} ({s}/3):** {note}")
        out.append(f"| {label} | " + " | ".join(row) + " |")
    out.append("| **Setup total** | " + " | ".join(f"**{t}/{3 * len(DIMENSIONS)}**" if "ide" in p else "n/a" for p, t in zip(cols, totals)) + " |")
    if any(p.get("review") for p in cols):
        out += ["", "## Goal scores (each person's own review)", "",
                "| Goal | " + " | ".join(p["name"] for p in cols) + " |", "|---|" + "---|" * len(cols)]
        for i in range(1, 14):
            out.append(f"| G{i} | " + " | ".join(
                str(next((g["score"] for g in (p.get("review") or {}).get("goals", []) if g["id"] == f"G{i}"), "n/a"))
                for p in cols) + " |")
        out.append("| **Total** | " + " | ".join(
            f"**{sum(g['score'] for g in p['review']['goals'])}/39**" if p.get("review") else "n/a" for p in cols) + " |")
    out += ["", "## Activity versus baseline" if people else "## Activity", ""]
    out.append("| Metric | " + " | ".join(p["name"] for p in cols) + " |")
    out.append("|---|" + "---|" * len(cols))
    for label, path in ACTIVITY:
        b = get(base, path)
        row = [human(b)]
        for p in people:
            v = get(p, path)
            pct = f" ({100 * v / b:.0f}%)" if v is not None and b else ""
            row.append(human(v) + pct)
        out.append(f"| {label} | " + " | ".join(row) + " |")
    out += ["", "## Hands-free readiness", ""]
    for p in cols:
        if "ide" not in p:
            continue
        missing = hands_free(p)
        out.append(f"- **{p['name']}:** " + ("ready: voice, own browser, desktop and all three channels connected."
                                              if not missing else "missing " + ", ".join(missing) + "."))
    out += ["", "## Details", ""]
    for p in cols:
        if notes[p["name"]]:
            out += [f"### {p['name']}", ""] + notes[p["name"]] + [""]
    return "\n".join(out)


def read_goals():
    """The goals rubric: beside this script in the public repo, under public/ in agent-setup."""
    here = os.path.dirname(os.path.abspath(__file__))
    for path in (os.path.join(here, "goals.md"), os.path.join(here, "public", "goals.md")):
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return f.read()
    return ""


def load(path):
    """A probe JSON file, a PDF report, or a hosted report link (its PDF is downloaded)."""
    if path.startswith("https://"):
        import tempfile
        import urllib.request
        url = path.rstrip("/") + ("" if path.rstrip("/").endswith("/pdf") else "/pdf")
        with urllib.request.urlopen(url, timeout=60) as r, tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(r.read())
        path = f.name
    if path.lower().endswith(".pdf"):
        docs = htmlreport.read_embedded_json(path) or read_raw_json(path)
        if not docs:
            sys.exit(f"{path}: no probe data found. Use the PDF exactly as the installer saved it, or the JSON.")
        return docs
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else [data]  # --dump output holds a list


def scan(docs):
    """Quick-scan rows [(label, [score or None per person], [note per person])] and totals per person."""
    rows = []
    for label, fn in DIMENSIONS:
        results = [fn(d) if "ide" in d else (None, "") for d in docs]
        rows.append((label, [r[0] for r in results], [r[1] for r in results]))
    totals = [f"{sum(r[1][i] for r in rows)}/{3 * len(DIMENSIONS)}" if "ide" in d else "n/a" for i, d in enumerate(docs)]
    return rows, totals


def activity(docs):
    base = docs[0]
    rows = []
    for label, path in ACTIVITY:
        b = get(base, path)
        vals = [human(b)]
        for d in docs[1:]:
            v = get(d, path)
            vals.append(human(v) + (f" ({100 * v / b:.0f}%)" if v is not None and b else ""))
        rows.append((label, vals))
    return rows


def solo_tiles(d):
    cc, par = d.get("claude_code") or {}, d.get("parallel_all_clients") or {}
    out_tokens = (cc.get("tokens_output") or 0) + 0
    return [("PRs merged", human(get(d, ("github", "prs_merged")))),
            ("Commits", human(get(d, ("github", "commits")))),
            ("Claude Code sessions", human(cc.get("sessions"))),
            ("Active days", human(cc.get("active_days"))),
            ("Output tokens", human(out_tokens) if cc else "n/a"),
            ("Most agents at once", human(par.get("peak_parallel_sessions")))]


def hands_free_lines(docs):
    return [f"{d['name']}: " + ("voice, own browser, desktop and all three channels connected." if not hands_free(d)
                                else "missing " + ", ".join(hands_free(d)) + ".") for d in docs if "ide" in d]


def main():
    args = sys.argv[1:]
    if args[:1] == ["--dump"] and len(args) == 2:
        print(json.dumps(load(args[1]), indent=1))
        return
    pdf = None
    coach = "--coach" in args
    args = [a for a in args if a != "--coach"]
    if "--pdf" in args:
        i = args.index("--pdf")
        pdf, args = args[i + 1], args[:i] + args[i + 2:]
    if not args:
        sys.exit(__doc__)
    loaded = [doc for p in args for doc in load(p)]
    goals = read_goals()
    review = ai_review(loaded[0], goals) if coach and len(loaded) == 1 else None
    if len(loaded) == 1 and not review:
        review = loaded[0].get("review")  # re-rendering a report keeps the review it already carries
    if review:
        loaded[0]["review"] = review  # travels in the PDF's machine copy, so comparisons can chart goal scores
    md = report(loaded[0], loaded[1:])
    if (coach or review) and len(loaded) == 1:
        # The personal review leads the report; the quick scan and activity follow as supporting detail.
        head, rest = md.split("## Quick scan", 1)
        md = f"{head.rstrip()}\n\n{review_markdown(review, goals) if review else guide_markdown(goals)}\n\n## Quick scan{rest}"
    print(md)
    if pdf:
        rows, totals = scan(loaded)
        page = htmlreport.build_html(loaded, review, goal_sections(goals), rows, totals, activity(loaded),
                                     solo_tiles(loaded[0]), hands_free_lines(loaded))
        if not htmlreport.print_pdf(page, pdf, loaded):
            write_pdf(pdf, md, loaded, appendix=goals)  # no Chromium browser: plain but complete PDF


if __name__ == "__main__":
    main()
