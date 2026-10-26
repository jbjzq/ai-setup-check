# AI setup goals

These goals describe a setup where one person directs many AI agents by voice, and those agents can reach every repo, browser, app and conversation that person can. Each goal is one thing such a setup does. A setup meets a goal when something in it serves the same purpose and is actually used. The tool does not have to be the same: different tools for the same job score the same.

Score each goal 0 to 3:

- **0:** nothing serves this goal.
- **1:** a tool exists but is unused, manual, or covers a small part of the goal.
- **2:** the goal is served and used, with gaps.
- **3:** the goal is served, used routinely, and close to automatic.

Evidence comes from the probe JSON: `inventory` lists every skill (name and description), MCP server, hook, custom agent, plugin, app, user CLI and editor or browser extension; the other sections hold usage counts. Judge a tool by what its description says it does, not by its name. Cite the evidence for every score.

## G1. Talk instead of type

**Why:** speaking is about three times faster than typing and keeps hands off the keyboard, so directing agents costs less effort than doing the work by hand.
**Counts:** any system-wide dictation or voice-command tool in daily use (Wispr Flow, superwhisper, MacWhisper, Aqua, VoiceInk, Talon, macOS Dictation used heavily).
**Does not count:** voice used only for meetings or transcription after the fact.
**Impact:** Directing ten agents means describing ten tasks; at speaking speed that takes minutes instead of half an hour, and long, precise prompts stop feeling expensive, so agents get better instructions.
**First step:** Install a system-wide dictation app, bind it to one key, and dictate your next three agent prompts instead of typing them.

## G2. Many workstreams without collisions

**Why:** several tasks in flight at once must not overwrite each other's files or branches, so each task gets its own isolated copy of the repo.
**Counts:** git worktrees, Conductor, Superset, devcontainers or cloud sandboxes per task, any tool that gives each agent task its own checkout.
**Does not count:** one checkout per repo with branch switching.
**Impact:** Two agents can work on the same repo at the same time without breaking each other's work, and an abandoned attempt is deleted in one step without touching anything else.
**First step:** Run `git worktree add ../<repo>-<task> -b <task>` for your next task and start the agent inside that folder, or adopt a tool that does this per task.

## G3. Several agents working at once

**Why:** the person is the orchestrator and the agents are the workers; throughput scales with how many agents run in parallel, not with typing speed.
**Counts:** any mix of agent CLIs, IDE agents or cloud agents running concurrently (`parallel_all_clients` in the JSON).
**Does not count:** several agents installed but used one at a time.
**Impact:** Output stops being capped by your attention on one session: while one agent builds, another tests and a third researches, which typically multiplies shipped work by the number of agents you can keep busy.
**First step:** Next time an agent is busy for more than two minutes, start a second session on a different task in its own worktree instead of waiting.

## G4. Think before building

**Why:** agents that code from a vague request wander; a written spec, then a plan, then execution keeps them on target and makes their work reviewable.
**Counts:** any repeatable spec → plan → execute flow: plan mode used routinely, custom commands or skills for each phase, spec and plan documents in repos, a task tracker the agent reads from.
**Does not count:** asking the agent to "think step by step" ad hoc.
**Impact:** Fewer rewrites: a spec catches misunderstandings before code exists, and a plan turns a big task into checkable steps, so agents finish larger tasks without drifting.
**First step:** Before your next feature, have the agent write a one-page spec, then a numbered plan, review both, and only then ask it to execute the plan.

## G5. Plans split into independent tasks

**Why:** a plan that records which tasks depend on which lets independent tasks run at the same time and blocked ones wait, so execution can be parallel and safe.
**Counts:** any plan format or tool that tracks dependencies between tasks and uses them to schedule work (task graphs, Linear sub-issues with blockers, Taskmaster-style tools).
**Does not count:** a flat to-do list.
**Impact:** Independent tasks run at the same time instead of one by one, and a task never starts before what it needs exists, so big plans finish in hours instead of days.
**First step:** In your next plan, add a "Blocked by" line to every task and start all tasks with no blockers in parallel.

## G6. Delegate inside a session

**Why:** handing research, review or a sub-task to a subagent keeps the main conversation's context clean and runs pieces in parallel.
**Counts:** subagents or background agents launched in parallel, custom agent definitions, any orchestration that fans work out.
**Does not count:** occasional single subagent use.
**Impact:** The main conversation stays short and focused, so it stays sharp for longer, and research or reviews run in parallel instead of in sequence.
**First step:** Ask your agent to send codebase research or a review to subagents, several at once, and to report back only a summary.

## G7. Knowledge that survives the session

**Why:** an agent that starts each session knowing the rules, the architecture and past lessons does not repeat mistakes or need re-explaining.
**Counts:** instruction files (AGENTS.md, CLAUDE.md, Cursor rules), memory tools or MCP memory servers, maintained architecture docs.
**Does not count:** one stale instruction file.
**Impact:** Agents stop repeating the same mistakes and you stop re-explaining the project, so each new session is productive from its first message.
**First step:** Each time you correct an agent twice for the same thing, write the rule in AGENTS.md or CLAUDE.md for that repo.

## G8. Fresh context before it bloats

**Why:** model quality drops as the context window fills; the setup notices and moves the task to a fresh session with a written handoff instead of letting it degrade.
**Counts:** any visible context gauge plus a deliberate habit or tool for clearing, compacting with instructions, or handing off (handoff files, /clear with notes, session summaries).
**Does not count:** only automatic compaction when the window is full.
**Impact:** Quality stays high in long tasks: a fresh session with a good handoff note performs like the start of the task, not like an agent that has forgotten half of it.
**First step:** Show context usage in your status line, and when it passes about 50%, ask the agent to write a handoff note and continue in a new session.

## G9. Independent checks and guardrails

**Why:** agents make confident mistakes; a second model's review, tests written first, and hooks that block dangerous actions catch them before they ship.
**Counts:** any cross-model or separate-agent review, enforced tests, pre-commit or agent hooks, CI gates the agent must pass.
**Does not count:** reviewing the agent's output by eye only.
**Impact:** Bugs and risky actions are caught by a machine before they reach you or production, so you can let agents run longer without watching every step.
**First step:** Add one review step by a different model or agent before each commit, and one hook that blocks a destructive command such as `rm -rf` or a push to main.

## G10. The agent uses the web as you

**Why:** most work needs logged-in websites; an agent driving the person's real browser profile can do it end to end, and a headless browser handles testing without disturbing anyone.
**Counts:** Claude in Chrome, Playwright or Chrome DevTools MCP attached to the real profile, Browserbase or similar for headless, browser-use agents.
**Does not count:** an agent that can only fetch pages without logins.
**Impact:** Tasks that touch logged-in tools (dashboards, admin panels, CRMs, test accounts) finish without you clicking through them, and every UI change can be tested by the agent itself.
**First step:** Install a browser tool your agent can drive in your own Chrome profile, and ask it to test your next UI change end to end.

## G11. The agent uses desktop apps

**Why:** some steps live in native apps and system dialogs; an agent that can see and click them never has to hand a step back to the person.
**Counts:** computer-use tools, macOS automation MCP servers, AppleScript or accessibility-based agent tools that are actually used.
**Does not count:** keyboard shortcut tools used only by the person.
**Impact:** The agent can finish steps that live in native apps, settings or system dialogs instead of stopping to ask you to click.
**First step:** Give your agent a tool that can see the screen and click in apps, and try it on one recurring task in a native app.

## G12. The agent reaches your conversations

**Why:** work starts and ends in conversations; an agent that can read and draft Slack, email and WhatsApp messages closes loops without copy and paste.
**Counts:** any CLI, MCP server or connector for each channel (Slack MCP, Gmail connector, WhatsApp bridge). One point per channel up to 3.
**Does not count:** notification-only integrations the agent cannot read.
**Impact:** Requests, answers and follow-ups move without copy and paste: the agent can read the thread that explains a task and draft the reply when it is done.
**First step:** Connect your agent to the one channel where most of your work requests arrive (often Slack or email), with sending kept behind your approval.

## G13. Agents keep working when you step away

**Why:** a remote machine and scheduled agents keep work moving while the laptop is closed, and a phone bridge lets the person answer agents from anywhere.
**Counts:** a VM, cloud dev box or cloud agents, scheduled or event-triggered agents, mobile notifications or approvals for agent sessions.
**Does not count:** a server that only hosts the product.
**Impact:** Work continues overnight and while you are in meetings, and agents that need a decision can reach you on your phone instead of waiting until you are back at your desk.
**First step:** Schedule one recurring agent task (a nightly check or report), and route agent notifications to your phone.

## Output

For each person: a table of G1 to G13 with score, the tool that serves the goal, and the evidence; then the three goals where an upgrade would help most, each with one concrete step. Usage numbers (tokens, sessions, PRs) show how much the setup is used; read them next to the scores, not as a goal.
