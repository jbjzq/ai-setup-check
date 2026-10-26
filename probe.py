#!/usr/bin/env python3
"""Read-only probe of a developer's AI coding environment on macOS.

Prints one JSON document to stdout. It records tool names, counts and token totals only:
no file contents, prompts, messages, hostnames, repo names or credentials.

Usage: python3 probe.py [--days 30] [--name "Jade"] [--no-github] > env-<name>.json
"""
import argparse
import json
from urllib.parse import urlsplit
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOME = Path.home()

IDES = ["Cursor", "Visual Studio Code", "Zed", "Windsurf", "Xcode", "IntelliJ IDEA", "PyCharm", "WebStorm",
        "GoLand", "Android Studio", "Sublime Text", "Nova", "Kiro", "Void", "Trae"]
AGENT_APPS = ["Superset", "Conductor", "Claude", "Codex", "Warp", "Ghostty", "iTerm", "Cline", "Terragon"]
AGENT_CLIS = ["claude", "codex", "grok", "gemini", "aider", "cursor-agent", "opencode", "amp", "goose", "droid",
              "copilot", "qwen"]
VOICE_APPS = ["Wispr Flow", "superwhisper", "MacWhisper", "Aqua Voice", "VoiceInk", "Willow", "Monologue",
              "Talon", "Whisper Transcription", "SpeakMac"]
VM_APPS = ["UTM", "Parallels Desktop", "VMware Fusion", "OrbStack", "Docker", "VirtualBox", "Tailscale",
           "Lima", "Tart"]
WORKSPACE_TOOLS = ["superset", "tmux", "zellij", "gh", "git-town", "mani", "meta", "gita", "ghq"]
COMMS_CLIS = {
    "whatsapp": ["wacli", "whatsapp-cli", "whatsapp", "mudslide"],
    "gmail": ["gog", "gmcli", "gmail", "gam", "himalaya", "mutt", "neomutt", "gcalcli"],
    "slack": ["slack", "slackcli", "slackdump", "slack-cli"],
}
HEADLESS_CLIS = ["agent-browser", "playwright", "browse", "puppeteer", "chromium", "browser-use", "stagehand"]
DESKTOP_CLIS = ["peekaboo", "cliclick", "macos-automator", "hs"]
DESKTOP_APPS = ["Hammerspoon", "Keyboard Maestro", "BetterTouchTool", "Peekaboo"]
CLAUDE_IN_CHROME_EXT = "fcoeoabgfenejglbffodgkkbkcdhcgfn"

# Name patterns that classify an MCP server, a skill or a plugin into a capability.
PATTERNS = {
    "own_browser": r"chrome|browsermcp|real.?browser|signed.?in|logged.?in|browser profile",
    "headless_browser": r"playwright|puppeteer|browserbase|headless|browser-use|stagehand|agent-browser|\bbrowse\b|steel",
    "desktop_control": r"desktop-|computer.?use|peekaboo|macos|automator|applescript|accessibility",
    "whatsapp": r"whatsapp|wacli",
    "gmail": r"gmail|google.?workspace|gog\b|email|mail",
    "slack": r"slack",
    "vm": r"\bvm\b|ec2|remote|ssh|devbox|codespace|sandbox|daytona|e2b|modal|virtual machine",
    "planning": r"plan|brainstorm|spec|execut|roadmap|design-doc",
    "voice": r"\bvoice|whisper|speech|dictat",
}


def sh(args, timeout=60):
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return out.stdout if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def apps_installed():
    found = set()
    for root in (Path("/Applications"), HOME / "Applications", Path("/Applications/Utilities")):
        if root.is_dir():
            found |= {p.stem for p in root.glob("*.app")}
    return found


def running_processes():
    return sh(["ps", "-axo", "comm"]).lower()


def match_apps(wanted, installed):
    return sorted(w for w in wanted if any(a.lower().startswith(w.lower()) for a in installed))


def which_all(names):
    return sorted(n for n in names if shutil.which(n))


def load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def mcp_servers():
    """MCP server names from Claude Code (user + every project), Claude Desktop, Codex and Cursor configs."""
    names = set()
    cj = load_json(HOME / ".claude.json")
    names |= set(cj.get("mcpServers", {}))
    for proj in cj.get("projects", {}).values():
        names |= set((proj or {}).get("mcpServers", {}))
    names |= set(load_json(HOME / "Library/Application Support/Claude/claude_desktop_config.json").get("mcpServers", {}))
    names |= set(load_json(HOME / ".cursor/mcp.json").get("mcpServers", {}))
    codex = HOME / ".codex/config.toml"
    if codex.exists():
        names |= set(re.findall(r"^\[mcp_servers\.([A-Za-z0-9_-]+)\]", codex.read_text(errors="replace"), re.M))
    return sorted(names)


def skill_names():
    """Skill folder names across Claude, Codex and the shared ~/.agents source, plus enabled Claude plugins."""
    names = set()
    for root in (HOME / ".claude/skills", HOME / ".agents/skills", HOME / ".codex/skills"):
        if root.is_dir():
            names |= {p.parent.name for p in root.glob("*/SKILL.md")}
    plugins = set(load_json(HOME / ".claude/settings.json").get("enabledPlugins", {}))
    commands = {p.stem for p in (HOME / ".claude/commands").glob("*.md")} if (HOME / ".claude/commands").is_dir() else set()
    return sorted(names), sorted(plugins), sorted(commands)


def classify(names):
    return {cap: sorted(n for n in names if re.search(rx, n, re.I)) for cap, rx in PATTERNS.items()}


DESCRIBED = {  # capabilities judged from a skill's description, which says what it does
    "own_browser": r"(real|your|user'?s|signed.?in|logged.?in)\W+(\w+\W+){0,2}(chrome|browser)|chrome profile",
    "headless_browser": r"headless (chrom\w*|browser)",
    "desktop_control": r"(native|desktop) apps?\b.{0,80}(click|screenshot|accessibility)|accessibility tree",
}


def classify_described(skills):
    return {cap: sorted(s["name"] for s in skills if re.search(rx, s.get("description", ""), re.I))
            for cap, rx in DESCRIBED.items()}


def chrome_has_claude_extension():
    base = HOME / "Library/Application Support/Google/Chrome"
    return any(base.glob(f"*/Extensions/{CLAUDE_IN_CHROME_EXT}")) if base.is_dir() else False


def git_repos(max_depth=4):
    """Count git checkouts and linked worktrees under $HOME, skipping Library and dependency folders."""
    skip = {"Library", "node_modules", ".Trash", ".cache", ".npm", ".venv", "venv", "Pods", ".cargo", ".rustup",
            "go", ".pyenv", ".nvm", "Movies", "Music", "Pictures"}
    repos, worktrees = [], []
    stack = [(str(HOME), 0)]
    while stack:
        d, depth = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        names = {e.name for e in entries}
        if ".git" in names:
            git = Path(d) / ".git"
            if git.is_dir():
                repos.append(Path(d))
            else:
                worktrees.append(Path(d))
            continue
        if depth >= max_depth:
            continue
        for e in entries:
            if e.is_dir(follow_symlinks=False) and e.name not in skip and not (e.name.startswith(".") and depth > 0
                                                                             and e.name not in (".superset", ".codex")):
                stack.append((e.path, depth + 1))
    return repos, worktrees


def ssh_host_count():
    cfg = HOME / ".ssh/config"
    if not cfg.exists():
        return 0
    hosts = re.findall(r"^\s*Host\s+(.+)$", cfg.read_text(errors="replace"), re.M | re.I)
    return sum(1 for h in hosts for name in h.split() if "*" not in name)


DAG_MARKERS = re.compile(r"Blocked by|Depends on|depends_on|Dependency Graph|\bWave \d|\bDAG\b", re.I)
SKILL_DAG = re.compile(r"Blocked by|depends_on|Dependency Graph|dependency (waves|order)", re.I)
# A handoff that fires on its own at a context threshold, not instructions for resuming one by hand.
AUTO_HANDOFF = re.compile(r"hand.?off[^\n]{0,80}\d+\s*%|\d+\s*%[^\n]{0,80}hand.?off|used_percentage|"
                          r"context\W{0,3}(window\W{0,3})?(reaches|exceeds|passes|above|over)\W{0,3}\d+\s*%", re.I)
INSTRUCTION_FILES = ("AGENTS.md", "CLAUDE.md", ".claude/CLAUDE.md", "CLAUDE.local.md")


def read(path, limit=400_000):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return ""


def skill_texts():
    """name -> SKILL.md text for every installed skill (matched locally for markers; never printed)."""
    out = {}
    for root in (HOME / ".claude/skills", HOME / ".agents/skills", HOME / ".codex/skills"):
        if root.is_dir():
            for f in root.glob("*/SKILL.md"):
                out.setdefault(f.parent.name, read(f))
    return out


def docs_in_repos(repos, since, worktrees=()):
    """Counts of spec, plan and handoff documents across checkouts and worktrees, and plans that declare
    task dependencies. A worktree holds copies of its repo's documents, so a file counts once per name and size."""
    counts = defaultdict(int)
    seen = set()
    worktree_set = set(worktrees)
    for repo in [*repos, *worktrees]:
        for kind in ("specs", "plans", "handoffs", "documentation"):
            d = repo / "docs" / kind
            if not d.is_dir():
                continue
            files = []
            for f in list(d.glob("**/*.md"))[:2000]:
                try:
                    key = (kind, f.name, f.stat().st_size)
                except OSError:
                    continue
                if key not in seen:
                    seen.add(key)
                    files.append(f)
            counts[f"repos_with_docs_{kind}"] += repo not in worktree_set
            counts[f"{kind}_files"] += len(files)
            counts[f"{kind}_files_in_window"] += sum(f.stat().st_mtime >= since.timestamp() for f in files)
            if kind == "plans":
                counts["plans_with_dependency_graph"] += sum(bool(DAG_MARKERS.search(read(f, 60_000))) for f in files)
        counts["repos_with_agent_instructions"] += repo not in worktree_set and any((repo / n).exists() for n in INSTRUCTION_FILES)
    plan_mode = HOME / ".claude/plans"
    counts["claude_plan_mode_files"] = len(list(plan_mode.glob("*.md"))) if plan_mode.is_dir() else 0
    return dict(counts)


def workflow_setup(repos, since, skills_used, worktrees=()):
    texts = skill_texts()
    names = sorted(texts)

    def having(rx):
        return [n for n in names if re.search(rx, n, re.I)]

    def used(found):
        return sum(v for k, v in skills_used.items() if k.split(":")[-1] in found)

    execute = having(r"execut|implement|ship|build")
    phases = {"spec": having(r"brainstorm|spec|design|idea"),
              "plan": [n for n in having(r"plan") if n not in execute], "execute": execute}
    settings = load_json(HOME / ".claude/settings.json")
    statusline = (settings.get("statusLine") or {}).get("command", "")
    statusline_file = re.search(r"(\S+\.sh)", statusline)
    statusline_text = statusline + read(os.path.expanduser(statusline_file.group(1))) if statusline_file else statusline
    global_instr = [p for p in ("~/.claude/CLAUDE.md", "~/.claude/AGENTS.md", "~/.codex/AGENTS.md", "~/AGENTS.md")
                    if Path(os.path.expanduser(p)).exists()]
    instr_text = "".join(read(os.path.expanduser(p)) for p in global_instr)
    memory_files = len(list((HOME / ".claude/projects").glob("*/memory/*.md")))
    hooks = settings.get("hooks") or {}
    agents_dir = HOME / ".claude/agents"
    launch_agents = HOME / "Library/LaunchAgents"
    return {
        "phases": {k: {"skills": v, "calls": used(v)} for k, v in phases.items()},
        "dag_skills": [n for n in names if SKILL_DAG.search(texts[n])],
        "handoff": {"skills": having(r"handoff|hand-off|resume"),
                    "auto_handoff_skills": [n for n in names if AUTO_HANDOFF.search(texts[n])],
                    "calls": used(having(r"handoff"))},
        "subagent_definitions": len(list(agents_dir.glob("*.md"))) if agents_dir.is_dir() else 0,
        "context": {"global_instruction_files": len(global_instr),
                    "compaction_rules": bool(re.search(r"compact", instr_text, re.I)),
                    "memory_files": memory_files,
                    "context_skills": having(r"context|memory|consolidat"),
                    "statusline_shows_context": bool(re.search(r"context_window|used_percentage|context", statusline_text))},
        "docs": docs_in_repos(repos, since, worktrees),
        "guardrails": {"hook_events": sorted(hooks),
                       "hook_commands": sum(len(m.get("hooks", [])) for v in hooks.values() for m in v),
                       "review_skills": having(r"review"),
                       "tdd_skills": having(r"test-driven|tdd"),
                       "output_style": settings.get("outputStyle"),
                       "scheduled_jobs": len([f for f in launch_agents.glob("*.plist")
                                              if not re.match(r"com\.(apple|google|microsoft)", f.name)])
                       if launch_agents.is_dir() else 0,
                       "automation_skills": having(r"automat|schedul|cron|loop|remind")},
    }


PACKAGE_ARG = re.compile(r"^@?[\w.-]+(/[\w.-]+)?(@[\w.^~-]+)?$")
SECRETISH = re.compile(r"key|token|secret|pass|auth|bearer", re.I)
LONG_TOKEN = re.compile(r"[A-Za-z0-9_]{24,}")  # long unbroken runs look like credentials, not package names
LAUNCHERS = {"npx", "uvx", "bunx", "pnpx", "pnpm", "bun", "deno", "pipx", "uv"}
BARE_FLAGS = {"-y", "--yes", "-q", "--quiet", "--silent", "-s"}


def frontmatter_description(text):
    m = re.search(r"^description:[ \t]*(.*)$((?:\n[ \t]+.*)*)", text[:3000], re.M)
    if not m:
        return ""
    first, rest = m.group(1).strip(), m.group(2)
    body = rest if first in ("|", ">", "|-", ">-", "") else first + rest
    return " ".join(body.split()).strip("'\"")[:300]


def hook_names(command):
    """Script names a hook runs (`notify.sh`, `bridge.py`), or its first word: never arguments or paths."""
    scripts = re.findall(r"([\w.-]+\.(?:sh|py|mjs|js|ts|rb))\b", command)
    if scripts:
        return scripts
    words = [w for w in command.replace('"', "").split() if "=" not in w]  # skip VAR=value prefixes
    if words and words[0] in ("if", "[", "[[", "test", "for", "while", "case", "{", "("):
        return ["inline shell"]
    return [os.path.basename(words[0])] if words else []


def launched_package(cmd, args):
    """The package a launcher (npx, uvx, bunx...) starts: its first positional argument, and only when it is
    shaped like a package name. Later arguments are never read, so option values such as API keys stay out."""
    if cmd not in LAUNCHERS or not isinstance(args, list):
        return None
    for i, a in enumerate(args):
        if not isinstance(a, str):
            return None
        if a.startswith("-"):
            if "=" not in a and a not in BARE_FLAGS:
                return None  # an option that may take the next argument as its value
            continue
        if PACKAGE_ARG.match(a) and not SECRETISH.search(a) and not LONG_TOKEN.search(a) and a not in ("dlx", "x", "run"):
            return a
        if a in ("dlx", "x", "run") and i == 0:
            continue
        return None
    return None


def mcp_inventory():
    """Each MCP server with what it runs: the command's base name and any package-like argument.
    Paths, URLs beyond the host, env values and anything that looks like a credential are left out."""
    servers = {}

    def add(name, cfg):
        cfg = cfg or {}
        cmd = os.path.basename(str(cfg.get("command") or ""))
        try:
            parsed = urlsplit(str(cfg.get("url") or ""))
            host = parsed.hostname if parsed.scheme in ("http", "https") else None
        except ValueError:
            host = None
        servers.setdefault(name, {"command": cmd or None, "package": launched_package(cmd, cfg.get("args")),
                                  "host": host})

    cj = load_json(HOME / ".claude.json")
    for name, cfg in cj.get("mcpServers", {}).items():
        add(name, cfg)
    for proj in cj.get("projects", {}).values():
        for name, cfg in ((proj or {}).get("mcpServers") or {}).items():
            add(name, cfg)
    for path in (HOME / "Library/Application Support/Claude/claude_desktop_config.json", HOME / ".cursor/mcp.json"):
        for name, cfg in load_json(path).get("mcpServers", {}).items():
            add(name, cfg)
    codex = read(HOME / ".codex/config.toml")
    for name, body in re.findall(r"^\[mcp_servers\.([A-Za-z0-9_-]+)\]\n((?:(?!\[).*\n?)*)", codex, re.M):
        cmd = re.search(r'^command\s*=\s*"([^"]+)"', body, re.M)
        add(name, {"command": cmd.group(1) if cmd else None,
                   "args": re.findall(r'"([^"]+)"', (re.search(r"^args\s*=\s*\[(.*)\]", body, re.M) or [None, ""])[1])})
    return [{"name": k, **v} for k, v in sorted(servers.items())]


def described(folder, pattern):
    out = []
    if folder.is_dir():
        for f in sorted(folder.glob(pattern)):
            name = f.parent.name if f.name == "SKILL.md" else f.stem
            out.append({"name": name, "description": frontmatter_description(read(f, 6000))})
    return out


def extension_ids(folder):
    if not folder.is_dir():
        return []
    return sorted({re.sub(r"-\d+(\.\d+)+.*$", "", p.name) for p in folder.iterdir() if p.is_dir()})


def chrome_extensions():
    names = set()
    base = HOME / "Library/Application Support/Google/Chrome"
    for manifest in list(base.glob("*/Extensions/*/*/manifest.json"))[:400] if base.is_dir() else []:
        name = load_json(manifest).get("name", "")
        if name and not name.startswith("__MSG_"):
            names.add(name[:60])
    return sorted(names)


def user_clis():
    """Tools the person installed on purpose: Homebrew leaves, global npm packages, uv/pipx tools, ~/.local/bin."""
    found = set(sh(["brew", "leaves"], timeout=30).split()) if shutil.which("brew") else set()
    npm = sh(["npm", "ls", "-g", "--depth=0", "--json"], timeout=30) if shutil.which("npm") else ""
    if npm:
        try:
            found |= set(json.loads(npm).get("dependencies", {}))
        except ValueError:
            pass
    if shutil.which("uv"):
        found |= {l.split()[0] for l in sh(["uv", "tool", "list"], timeout=30).splitlines() if l and not l.startswith("-")}
    for d in (HOME / ".local/bin", HOME / "bin", HOME / ".cargo/bin", HOME / "go/bin"):
        if d.is_dir():
            found |= {p.name for p in d.iterdir() if not p.name.startswith(".")}
    return sorted(found)[:600]


def inventory():
    """Everything installed that could serve a goal, with descriptions where the tool has one, so the
    evaluation can judge tools by purpose instead of by name."""
    skills = {}
    for root in (HOME / ".claude/skills", HOME / ".agents/skills", HOME / ".codex/skills"):
        for item in described(root, "*/SKILL.md"):
            skills.setdefault(item["name"], item)
    settings = load_json(HOME / ".claude/settings.json")
    hooks = {event: sorted({n for m in v for h in m.get("hooks", []) for n in hook_names(h.get("command", ""))})
             for event, v in (settings.get("hooks") or {}).items()}
    launch = HOME / "Library/LaunchAgents"
    return {
        "skills": list(skills.values()),
        "custom_agents": described(HOME / ".claude/agents", "*.md"),
        "slash_commands": [c["name"] for c in described(HOME / ".claude/commands", "*.md")],
        "mcp_servers": mcp_inventory(),
        "hooks": hooks,
        "plugins": sorted(settings.get("enabledPlugins", {})),
        "apps": sorted(apps_installed()),
        "user_clis": user_clis(),
        "editor_extensions": {"cursor": extension_ids(HOME / ".cursor/extensions"),
                              "vscode": extension_ids(HOME / ".vscode/extensions"),
                              "windsurf": extension_ids(HOME / ".windsurf/extensions")},
        "chrome_extensions": chrome_extensions(),
        "scheduled_jobs": sorted(f.stem for f in launch.glob("*.plist")
                                 if not re.match(r"com\.(apple|google|microsoft)", f.name)) if launch.is_dir() else [],
    }


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def iter_jsonl(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            try:
                rec = json.loads(raw)
            except ValueError:
                continue
            if isinstance(rec, dict):
                yield rec


def claude_activity(since):
    """Sessions, active days, tokens and peak parallel sessions from ~/.claude/projects transcripts."""
    root = HOME / ".claude/projects"
    fields = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    stamps = defaultdict(list)
    days = set()
    tools = defaultdict(int)
    tokens = {"total": 0, "output": 0}
    by_model = defaultdict(int)
    seen = set()
    skills_used = defaultdict(int)
    agents_per_msg = defaultdict(int)  # one response spans several lines sharing message.id
    agent_opts = defaultdict(int)
    compactions = defaultdict(int)
    compacted_sessions = set()
    peak_context = defaultdict(int)
    if not root.is_dir():
        return None
    for path in root.glob("**/*.jsonl"):
        if path.stat().st_mtime < since.timestamp():
            continue
        is_sub = "subagents" in path.parts
        for rec in iter_jsonl(path):
            ts = rec.get("timestamp")
            if not ts:
                continue
            try:
                t = parse_ts(ts)
            except ValueError:
                continue
            if t < since:
                continue
            sid = rec.get("sessionId")
            if rec.get("subtype") == "compact_boundary" and not is_sub:
                compactions[(rec.get("compactMetadata") or {}).get("trigger") or "unknown"] += 1
                compacted_sessions.add(sid)
            if sid and not is_sub and rec.get("type") in ("user", "assistant"):
                stamps[sid].append(t)
                days.add(t.date().isoformat())
            msg = rec.get("message")
            if rec.get("type") != "assistant" or not isinstance(msg, dict):
                continue
            for block in msg.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    name = block.get("name", "")
                    if name in ("Agent", "Task", "Skill", "ExitPlanMode", "Workflow") or name.startswith("mcp__"):
                        tools[name.split("__")[1] if name.startswith("mcp__") else name] += 1
                    inp = block.get("input") if isinstance(block.get("input"), dict) else {}
                    if name == "Skill" and inp.get("skill"):
                        skills_used[str(inp["skill"])[:60]] += 1
                    if name in ("Agent", "Task"):
                        agents_per_msg[msg.get("id") or id(block)] += 1
                        agent_opts["worktree_isolation"] += inp.get("isolation") == "worktree"
                        agent_opts["background"] += inp.get("run_in_background") is True
            mid = msg.get("id")
            if mid in seen:
                continue
            seen.add(mid)
            usage = msg.get("usage") or {}
            n = sum(usage.get(k) or 0 for k in fields)
            if sid and not is_sub:
                ctx = n - (usage.get("output_tokens") or 0)
                peak_context[sid] = max(peak_context[sid], ctx)
            tokens["total"] += n
            tokens["output"] += usage.get("output_tokens") or 0
            by_model[msg.get("model") or "unknown"] += n
    return {
        "sessions": len(stamps),
        "active_days": len(days),
        "tokens_total": tokens["total"],
        "tokens_output": tokens["output"],
        "tokens_by_model": dict(sorted(by_model.items(), key=lambda kv: -kv[1])[:6]),
        "subagent_calls": tools.get("Agent", 0) + tools.get("Task", 0),
        "skill_calls": tools.get("Skill", 0),
        "plan_mode_exits": tools.get("ExitPlanMode", 0),
        "workflow_calls": tools.get("Workflow", 0),
        "mcp_calls_by_server": dict(sorted(((k, v) for k, v in tools.items()
                                            if k not in ("Agent", "Task", "Skill", "ExitPlanMode", "Workflow")),
                                           key=lambda kv: -kv[1])[:15]),
        "skill_calls_by_name": dict(sorted(skills_used.items(), key=lambda kv: -kv[1])),
        "parallel_agent_dispatches": sum(1 for n in agents_per_msg.values() if n >= 2),
        "max_agents_in_one_message": max(agents_per_msg.values(), default=0),
        "agents_in_worktrees": agent_opts["worktree_isolation"],
        "agents_in_background": agent_opts["background"],
        "compactions": dict(compactions),
        "sessions_compacted": len(compacted_sessions),
        **context_stats(peak_context.values()),
        **concurrency(stamps.values()),
        "_stamps": stamps,
    }


def context_stats(peaks):
    """Largest context each main session reached: how often work runs in a bloated window."""
    peaks = sorted(p for p in peaks if p)
    if not peaks:
        return {}
    return {"median_peak_context_tokens": peaks[len(peaks) // 2],
            "sessions_over_200k_context": sum(p > 200_000 for p in peaks),
            "sessions_over_500k_context": sum(p > 500_000 for p in peaks)}


def codex_activity(since):
    root = HOME / ".codex/sessions"
    if not root.is_dir():
        return None
    stamps, total = defaultdict(list), 0
    for path in root.glob("**/*.jsonl"):
        if path.stat().st_mtime < since.timestamp():
            continue
        prev = 0
        for rec in iter_jsonl(path):
            ts = rec.get("timestamp")
            if not ts:
                continue
            try:
                t = parse_ts(ts)
            except ValueError:
                continue
            # The counter is cumulative per session: advance it before the window check, so a session
            # that started before the window only adds the tokens spent inside it.
            p = rec.get("payload") or {}
            delta = 0
            if rec.get("type") == "event_msg" and p.get("type") == "token_count":
                cur = (((p.get("info") or {}).get("total_token_usage")) or {}).get("total_tokens") or 0
                delta, prev = max(cur - prev, 0), max(prev, cur)
            if t < since:
                continue
            stamps[path].append(t)
            total += delta
    return {"sessions": len(stamps), "tokens_total": total, **concurrency(stamps.values()), "_stamps": stamps}


def concurrency(sessions, idle=timedelta(minutes=10)):
    """Peak sessions working at once, and hours with 2+ and 3+ working. Each session's message timestamps
    become active spans; a gap longer than `idle` ends a span, so a terminal left open overnight does not count."""
    events = []
    for times in sessions:
        times = sorted(times)
        lo = hi = times[0]
        for t in times[1:] + [None]:
            if t is not None and t - hi <= idle:
                hi = t
                continue
            events += [(lo, 1), (max(hi, lo + timedelta(minutes=1)), -1)]
            if t is not None:
                lo = hi = t
    events.sort()
    cur = peak = 0
    two = three = 0.0
    prev_t = None
    for t, delta in events:
        if prev_t is not None:
            h = (t - prev_t).total_seconds() / 3600
            two += h if cur >= 2 else 0
            three += h if cur >= 3 else 0
        cur += delta
        peak = max(peak, cur)
        prev_t = t
    return {"peak_parallel_sessions": peak, "hours_2plus_parallel": round(two, 1), "hours_3plus_parallel": round(three, 1)}


def github_activity(days, login=None):
    """Search API totals, one request each. The profile contribution graph undercounts badly (commits from
    unlinked emails, private repos, squash merges), so it is not used."""
    if not shutil.which("gh"):
        return None
    login = login or sh(["gh", "api", "user", "--jq", ".login"]).strip()
    if not login:
        return None
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()

    def total(endpoint, q):
        out = sh(["gh", "api", "-X", "GET", f"search/{endpoint}", "-f", "per_page=1", "-f", f"q={q}",
                  "--jq", ".total_count"]).strip()
        return int(out) if out.isdigit() else None

    return {
        "login": login,
        "commits": total("commits", f"author:{login} author-date:>={since}"),
        "prs_opened": total("issues", f"author:{login} is:pr created:>={since}"),
        "prs_merged": total("issues", f"author:{login} is:pr is:merged merged:>={since}"),
        "prs_reviewed": total("issues", f"reviewed-by:{login} -author:{login} is:pr updated:>={since}"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--name", default=os.environ.get("USER", "unknown"))
    ap.add_argument("--github-login", help="GitHub user to read instead of the gh-authenticated one")
    ap.add_argument("--github-only", action="store_true", help="Skip the local scan, read GitHub only")
    ap.add_argument("--no-github", action="store_true")
    args = ap.parse_args()
    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    result = {"name": args.name, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "window_days": args.days, "platform": sys.platform}
    if not args.no_github:
        result["github"] = github_activity(args.days, args.github_login)
    if args.github_only:
        print(json.dumps(result, indent=2))
        return
    installed = apps_installed()
    procs = running_processes()
    servers = mcp_servers()
    skills, plugins, commands = skill_names()
    inv = inventory()
    claude = claude_activity(since)
    codex = codex_activity(since)
    # Parallelism across both clients together: one Claude and one Codex session at once is two agents.
    all_stamps = [*(claude or {}).pop("_stamps", {}).values(), *(codex or {}).pop("_stamps", {}).values()]
    used = list((claude or {}).get("mcp_calls_by_server", {}))
    caps = classify(sorted(set(servers + skills + plugins + commands + used)))
    # Skills are also matched on what their description says (browser, desktop, voice...), so a tool with any name
    # counts; the description only selects the skill, and only its name is reported.
    for cap, found in classify_described(inv["skills"]).items():
        caps[cap] = sorted(set(caps[cap]) | set(found))
    repo_roots, worktrees = git_repos()
    result.update({
        "ide": {"installed": match_apps(IDES, installed),
                "running": [i for i in IDES if i.lower() in procs]},
        "agent_apps": match_apps(AGENT_APPS, installed),
        "agent_clis": which_all(AGENT_CLIS),
        "multi_repo": {"git_checkouts": len(repo_roots), "linked_worktrees": len(worktrees),
                       "tools": which_all(WORKSPACE_TOOLS) + match_apps(["Superset", "Conductor", "GitHub Desktop"], installed)},
        "voice": {"apps": match_apps(VOICE_APPS, installed),
                  "running": [v for v in VOICE_APPS if v.lower().split()[0] in procs],
                  "skills_or_mcp": caps["voice"]},
        "planning": {"skills_or_commands": caps["planning"], "skill_count": len(skills),
                     "plugin_count": len(plugins), "command_count": len(commands)},
        "browser": {"own_browser": caps["own_browser"] + (["Claude in Chrome extension"] if chrome_has_claude_extension() else []),
                    "headless": caps["headless_browser"] + which_all(HEADLESS_CLIS)},
        "vm": {"apps": match_apps(VM_APPS, installed), "ssh_hosts": ssh_host_count(),
               "aws_cli_configured": (HOME / ".aws/credentials").exists() or (HOME / ".aws/config").exists(),
               "skills_or_mcp": caps["vm"]},
        "desktop_control": {"mcp_or_skills": caps["desktop_control"], "clis": which_all(DESKTOP_CLIS),
                            "apps": match_apps(DESKTOP_APPS, installed)},
        "comms": {k: {"clis": which_all(v), "mcp_or_skills": caps[k]} for k, v in COMMS_CLIS.items()},
        "mcp_servers": servers,
        "inventory": inv,
        "workflow": workflow_setup(repo_roots, since, (claude or {}).get("skill_calls_by_name", {}), worktrees),
        "parallel_all_clients": concurrency(all_stamps),
        "claude_code": claude,
        "codex": codex,
    })
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
