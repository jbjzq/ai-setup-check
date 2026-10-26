# ai-setup-check

Checks whether an AI coding setup reaches the goals in [goals.md](goals.md), by any tools: talking instead of typing, many isolated workstreams, parallel agents, spec → plan → execute, dependency-aware plans, subagents, lasting knowledge, fresh context, independent checks, and agents that reach the web, the desktop, your conversations and a machine that keeps working when you step away. A quick keyword scan covers 15 dimensions: IDE, multi-repo work, parallel agent sessions, voice input, spec → plan → execute workflow, task dependency graphs, parallel subagents, handoffs, context layers, context switching, guardrails, browser control, virtual machines, desktop control, and Slack/Gmail/WhatsApp access. It also counts GitHub, Claude Code and Codex activity over the last 30 days.

## Install and run (one line)

    curl -fsSL https://raw.githubusercontent.com/jbjzq/ai-setup-check/main/install.sh | bash

This installs the `ai-setup-check` skill for Claude Code (and Codex, if present), scans your setup once, prints your report, and saves `~/Desktop/ai-setup-<name>.pdf`. The PDF opens with a personal review written by your own Claude Code: a score for each goal, the three to five changes with the most impact (why, expected impact, how to start) and quick wins. Then come the quick scan and activity counts, with the raw probe data as JSON on the last pages so an AI can analyze it. Afterwards, ask your agent to "run ai-setup-check" to rerun it or to get suggestions.

## What it reads

Everything stays on your machine until you choose to send the PDF. The probe is read-only and needs only Python 3.9+.

- Installed apps and command-line tools (names only).
- MCP server, skill, plugin and hook names from your Claude Code, Codex and Cursor configs.
- Claude Code and Codex session logs, for counts and token totals: no prompts, replies or file contents.
- Git checkouts under your home folder (counts), and spec/plan/handoff documents (counts, plus whether a plan lists task dependencies).
- GitHub search totals for your account, through `gh` if it is logged in.

To write the review, the installer sends the scan results and goals.md to your own Claude Code (`claude -p`, no tools, no file access). Without Claude Code, the PDF includes a guide to every goal instead. The PDF is laid out as a web page and printed by Chrome, Edge, Brave or Chromium if one is installed (a throwaway profile, your browser is not touched); without one it is plain text.

At the end the installer asks whether to upload the PDF for a shareable link. Answering yes sends only that PDF to a private Evaboot bucket; the link is an unguessable address, the report is deleted after a year, and answering no keeps everything on your machine.

Open the PDF before sending it to see exactly what it contains.
