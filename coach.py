"""The educational part of the report: what this person could improve, why, and the expected impact.

The person's own Claude Code judges their probe data against goals.md and returns a structured review
(a score per goal, improvements, quick wins) that the report draws as charts and cards. When Claude Code is
missing or fails, the report falls back to the guide written in goals.md: why, impact and a first step for
every goal, generic but still teaching what each goal is for.
"""
import json
import re
import shutil
import subprocess
import tempfile

PROMPT = """You are reviewing a developer's AI coding setup to teach them how to get more out of it. Below are
a rubric of 13 goals (G1 to G13), then the developer's probe data as JSON: an inventory of every installed
skill, agent, MCP server, hook, app, CLI and extension (with descriptions), plus usage counts for the last
{days} days.

Write to the developer as "you", in plain, encouraging English, specific to the tools they actually have.
Judge each tool by its description and usage, not by its name: different tools that reach the same goal
score the same. Never suggest a tool for a goal they already serve well, and never name any other person.
Never compare with another setup or mention anyone else's tools, skills or scripts: describe each technique in plain
words and, when you name a tool, name one the developer already has or a widely available product.

Reply with one JSON object and nothing else, in exactly this shape:
{{
  "summary": "two or three sentences: what the setup already does well, and the single biggest opportunity",
  "goals": [{{"id": "G1", "score": 0, "tools": "what serves this goal today, short", "evidence": "the data behind the score, one or two sentences",
             "improve": {{"steps": ["three to five concrete steps, in order, each one or two sentences, using their tools and naming files, settings or commands"],
                         "result": "what changes once this is done, one or two sentences"}}}}],
  "improvements": [{{"title": "the change, as an action", "why": "what goes wrong or stays slow today, citing their data",
                    "impact": "the concrete effect to expect: time saved, fewer mistakes, more work in parallel",
                    "how": "one first step that fits the tools they already use, naming the tool or command"}}],
  "quick_wins": ["a change that takes under 15 minutes"]
}}
"goals" has one entry per goal G1 to G13, scored 0 to 3 as the rubric says. "improvements" holds the three to
five changes with the highest impact, highest first. "quick_wins" holds up to three items. For a goal scored 3,
"improve" says how to go further.

RUBRIC
{goals}

PROBE DATA
{data}
"""


def parse_review(text):
    """The review object from Claude's answer, or None when it is missing or malformed."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        r = json.loads(text[start:end + 1])
    except ValueError:
        return None
    if not isinstance(r, dict) or any(not isinstance(r.get(k, []), list) for k in ("goals", "improvements", "quick_wins")):
        return None
    goals = {g["id"]: g for g in r.get("goals") or [] if isinstance(g, dict) and isinstance(g.get("id"), str)}
    ids = [f"G{i}" for i in range(1, 14)]
    if not isinstance(r.get("summary"), str) or any(not isinstance(goals.get(i, {}).get("score"), int)
                                                    or not 0 <= goals[i]["score"] <= 3 for i in ids):
        return None
    improvements = [i for i in r.get("improvements") or []
                    if isinstance(i, dict) and all(isinstance(i.get(k), str) for k in ("title", "why", "impact", "how"))]
    if not improvements:
        return None
    return {"summary": r["summary"],
            "goals": [{"id": i, "score": goals[i]["score"], "tools": str(goals[i].get("tools") or ""),
                       "evidence": str(goals[i].get("evidence") or ""), "improve": improve_of(goals[i].get("improve"))}
                      for i in ids],
            "improvements": improvements[:5],
            "quick_wins": [str(q) for q in r.get("quick_wins") or []][:3]}


def improve_of(value):
    """{"steps": [...], "result": "..."} from the review; an older review's plain string becomes one step."""
    if isinstance(value, str):
        return {"steps": [value] if value else [], "result": ""}
    if not isinstance(value, dict):
        return {"steps": [], "result": ""}
    steps = [str(x) for x in value.get("steps") or [] if isinstance(x, (str, int, float))] if isinstance(value.get("steps"), list) else []
    return {"steps": steps[:6], "result": str(value.get("result") or "")}


def ai_review(doc, goals, timeout=420):
    """Structured review written by the local Claude Code, or None when it is unavailable or unusable."""
    claude = shutil.which("claude")
    if not claude or not goals:
        return None
    prompt = PROMPT.format(days=doc.get("window_days", 30), goals=goals, data=json.dumps(doc, separators=(",", ":")))
    # Safe mode (no CLAUDE.md, hooks, skills or MCP), no tools and a scratch folder: the review sees only this
    # prompt, so nothing private from the person's own setup leaks into the report. A Claude Code too old for
    # --safe-mode fails here and the goals guide is used instead.
    with tempfile.TemporaryDirectory() as scratch:
        try:
            out = subprocess.run([claude, "-p", "--safe-mode", "--output-format", "text", "--tools", "",
                                  "--no-session-persistence", "--disable-slash-commands", "--strict-mcp-config"],
                                 input=prompt, capture_output=True, text=True, timeout=timeout, cwd=scratch)
        except (OSError, subprocess.SubprocessError):
            return None
    return parse_review(out.stdout) if out.returncode == 0 else None


def goal_sections(goals):
    """[(id, title, {label: text})] for every goal in goals.md."""
    out = []
    for gid, title, body in re.findall(r"^## (G\d+)\. ([^\n]+)\n(.*?)(?=^## |\Z)", goals, re.M | re.S):
        fields = dict(re.findall(r"^\*\*([A-Za-z ]+):\*\* (.+)$", body, re.M))
        out.append((gid, title, fields))
    return out


def review_markdown(r, goals):
    titles = {gid: title for gid, title, _ in goal_sections(goals)}
    steps = {gid: f.get("First step", "") for gid, _, f in goal_sections(goals)}
    out = ["## Your goal review", "", r["summary"], ""]
    for g in r["goals"]:
        imp = improve_of(g.get("improve"))
        out += [f"### {g['id']}. {titles.get(g['id'], '')}: {g['score']}/3", "**A way to improve:**"]
        out += [f"{n}. {step}" for n, step in enumerate(imp["steps"] or [steps.get(g["id"], "")], 1)]
        if imp["result"]:
            out.append(f"**What it changes:** {imp['result']}")
        out += [f"**Your current stack:** {g['tools'] or 'nothing yet'}. {g['evidence']}", ""]
    out += ["", "## What to improve", ""]
    for n, i in enumerate(r["improvements"], 1):
        out += [f"### {n}. {i['title']}", f"**Why:** {i['why']}", f"**Impact:** {i['impact']}",
                f"**How to start:** {i['how']}", ""]
    if r["quick_wins"]:
        out += ["## Quick wins", ""] + [f"- {q}" for q in r["quick_wins"]] + [""]
    return "\n".join(out)


def guide_markdown(goals):
    """Why, impact and first step for every goal, taken from goals.md."""
    out = ["## Ways to improve", "",
           "Claude Code was not available to personalize this section, so it lists every goal with why it "
           "matters, what it changes and a first step. Skip the ones your setup already covers.", ""]
    for gid, title, f in goal_sections(goals):
        out += [f"### {gid}. {title}"] + [f"**{k}:** {f[k]}" for k in ("Why", "Impact", "First step") if k in f] + [""]
    return "\n".join(out)
