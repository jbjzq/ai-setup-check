---
name: ai-setup-check
description: Use when the user wants to check or score their AI coding setup, rerun the setup probe JB asked for, or find out what to add to work hands-free with agents (voice, parallel agents, planning workflow, browser and desktop control, Slack/Gmail/WhatsApp access).
---

# AI setup check

Two scripts in this folder measure an AI coding setup on macOS. `probe.py` only reads: it prints JSON with tool names, counts and token totals, never file contents, prompts, messages, hostnames or repo names. `score.py` turns that JSON into a 15-dimension report, each scored 0 to 3.

## Run it

    python3 -I probe.py --name "<your name>" > /tmp/ai-setup.json
    python3 -I score.py /tmp/ai-setup.json --coach --pdf ~/Desktop/ai-setup-<name>.pdf

Run both from this skill's folder. `--coach` asks Claude Code to write the personal review (scores per goal, what to improve, why, impact, first step) at the top of the PDF. `gh auth login` adds GitHub activity; without it that section is skipped. Show the user the scores and the "Hands-free readiness" line, and remind them to send the PDF, or the link printed by the installer's upload step, to JB. Its last pages hold the raw probe JSON, so an AI can analyze the PDF directly.

## Goal check

The scores above match known tool names only. For the real check, read `goals.md` in this folder: it lists 13 goals (G1 to G13), what each is for, and what counts. Judge the user's setup against each goal using the `inventory` and usage counts in the JSON, by what each tool does rather than its name, and score 0 to 3 with evidence. Different tools that reach the same goal score the same.

## Improving a low score

For each goal under 3, name one concrete next step that fits the tools the user already has. Do not install anything without the user's go-ahead.
