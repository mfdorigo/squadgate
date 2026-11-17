# squadgate

**A development squad for Claude Code: AI agents with human approval gates, safety guardrails, and measured cost.**

You describe a demand. An orchestrator moves it through five specialist agents (Analyst, UX, Architect, Developer, QA) and stops at fixed **gates** where you approve, adjust or cancel. Between gates the squad works on its own, inside guardrails that block risky commands, and you can watch it live in a local panel.

```
/squad Add CSV export to the monthly report
```

- Works in **any project**: the project's own context comes from its `CLAUDE.md`.
- Runs **only when you type `/squad`**. Outside a demand, nothing changes in your Claude Code.
- **Portuguese or English, no setup**: the squad writes in the language of your demand.

---

## How it works

| Gate | When | You approve |
|---|---|---|
| **Gate 0** | Right after `/squad` | Understanding, size (S/M/L), roles and branch |
| **Gate 1** | After the Analyst (and UX, when a screen changes) | The story: scope and acceptance criteria; the screen sketch and, on request, a prototype |
| **Gate 2** | After the Architect's plan (L only) | The blocks of work, and **sequential or 2 developers in parallel** |
| **Gate 3** | Delivery ready | The result; you merge the PR with squash |

Between Gate 2 and Gate 3 the squad runs on its own: tests first, implementation block by block, code review, validation, PR. It stops earlier only after 3 failed attempts on a block, the same failure twice, or a question only you can answer.

**Size decides the flow:**

| Size | Flow | Gates |
|---|---|---|
| **S** (small fix) | Developer → review → PR | 0, 3 |
| **M** (feature, no design decision) | Story → tests → developer → review → validation → PR | 0, 1, 3 |
| **L** (new feature, data model, contract) | Full flow with the Architect's plan | 0, 1, 2, 3 |

`--step-by-step` also stops after each block and after the review.

### The team

| Role | Model | What it does | Writes |
|---|---|---|---|
| Orchestrator (`/squad` skill) | Sonnet | Coordinates, records, asks for approval. Makes no technical decisions. | `progresso.md`, `painel.json` |
| Analyst | Opus | Questions the premise, finds the smallest valuable scope, writes testable acceptance criteria. | `historia.md` |
| UX | Opus | When the story touches a screen: sketches it in text (ASCII), justifying every element, and on request builds a clickable HTML prototype in the project's own visual style. | `telas.md`, `prototipo.html` |
| Architect | Opus | Simplest solution that works, split into blocks; later reviews the code, security and commits. | `plano.md`, `review.md` |
| Developer | Sonnet | One block per call, one commit per block. | code |
| QA | Sonnet | Tests from the criteria before the code; then validates criterion by criterion. | tests |

Reasoning effort is chosen per task: high where a mistake is expensive (understanding, design, large demands, a block that already failed), medium for execution with a defined scope. The table lives in one place, rule 12 of `skills/squad/SKILL.md`.

Each demand gets a folder in the project, `docs/demandas/<id>/`, and a branch, `squad/<id>-<slug>`. File names are fixed in every language.

---

## Install

**Requirements:** [Claude Code](https://docs.anthropic.com/en/docs/claude-code), git, bash and Python 3 (standard library only).

```bash
git clone <this repository> ~/code/squadgate
cd ~/code/squadgate
./install.sh
```

Then open a **new** Claude Code session and type `/squad`.

What the installer does:

- Links (macOS/Linux) or copies (Windows) the agents, the skill and the scripts into `~/.claude`.
- Adds the squadgate hooks to `~/.claude/settings.json`, **keeping every other setting**. The previous file is saved first.
- Anything already in those places is moved to `~/.claude/squad-state/backup/<date>/`, never deleted.
- Running it again is safe: it replaces the previous squadgate install.

**Update:** `git pull`. With links, that is all. On Windows (copy mode) run `./install.sh` again.

## Uninstall

```bash
./uninstall.sh            # removes agents, skill, scripts and hooks; keeps history and backups
./uninstall.sh --purge    # also deletes ~/.claude/squad-state
```

Only what the installer added is removed. Your other agents, skills and settings stay.

---

## Commands

| Command | What it does |
|---|---|
| `/squad <demand>` | Starts a demand with approval gates. |
| `/squad --step-by-step <demand>` | Same, also stopping after each block and after review. |
| `/squad continue <id>` | Resumes an interrupted demand. |
| `/squad cancel <id>` | Ends the demand without deleting anything and turns guardrails off. |
| `/squad status` | Demands in this project and what waits for you. |
| `/squad cost` | Tokens per agent and model in this session; warns if the Orchestrator left Sonnet or an agent ran in the background. Uses no quota. |
| `/squad report` | Snapshot of progress to share. |
| `/squad panel` · `panel off` | Turns the live panel on (opens it) or off. |
| `/squad alerts` · `alerts off` | Turns system sound and notifications on or off (on by default). |

Portuguese names work too: `continuar`, `cancelar`, `custo`, `relatorio`, `painel`, `avisos`, `--passo-a-passo`.

---

## Guardrails

Active **only while a `/squad` demand is in progress in that project**, enforced by hooks (not by the prompt):

- Commits must follow Conventional Commits with a `Refs: <id>` footer; generic messages ("fixes", "ajustes", "WIP") are rejected.
- Blocked: push to `main`/`master`, forced push, `rm -rf`, `git reset --hard`, `git clean -f`, `terraform apply/destroy`, `kubectl delete` and commands that look like they touch production.
- Squad agents must run in the foreground (see the case study for why this matters for cost).

The squad never merges, deploys or pushes to the main branch. The merge is yours, at Gate 3.

## Live panel

`/squad panel` opens a local page that refreshes every 3 seconds from a file the hooks write. It shows where the demand is, what needs you, which agents are working (with an estimated finish after two runs of a role), the steps and blocks, and recent activity. A **Commands** button (or the `?` key) lists every command and the gates; clicking a command copies it. **PT / EN** switches the panel language.

It reads local files only and **uses no Claude quota**.

## Cost

`/squad cost` reads the session transcripts on your machine and prints tokens per agent and per model since the demand started, plus two checks: did the Orchestrator stay on Sonnet, and did any agent run in the background. Run it at the end of each demand to build your own baseline.

## Language

- The squad writes in the language of your demand: story, plan, gates, status, commits.
- Commit language follows the project: its `CLAUDE.md`, else the language of the existing commits, else the demand's.
- The panel starts in your browser language and has a PT / EN switch that changes the whole panel, whatever the demand's language: the orchestrator writes the panel texts in both languages, and the panel names the steps and roles itself. Agent task descriptions (team cards and activity) stay in the demand's language. Notifications follow the OS language.
- The agent prompts are written in Brazilian Portuguese, the language they were validated in. They instruct the agents to answer in the demand's language.

---

## Design decisions

- **The Orchestrator is the main session, not a subagent.** Subagents cannot talk to you mid-flow or call other agents; the main session can do both.
- **Gates are hard stops.** Each gate uses Claude Code's question dialog and does not move on without an answer.
- **Parallelism is your decision**, taken at Gate 2. The Architect only suggests which blocks are independent.
- **Anti-loop limits:** 3 attempts per block, the same failure twice stops the flow, at most 2 review rounds, `maxTurns` on every agent.
- **Agents write their own files** and return a short summary. The Orchestrator never re-reads or re-types them, which keeps its context small.
- **Guardrails live in hooks**, so they hold even if a prompt is ignored, and they switch off when no demand is active.
- **No external dependencies:** bash and the Python standard library.

## Platform support

| | Status |
|---|---|
| macOS | Supported and tested. |
| Linux | Supported. Notifications need `notify-send`, sound needs `paplay`, the panel opens with `xdg-open`; each is skipped if missing. |
| Windows | **Not tested.** Uses Git Bash (required by Claude Code on Windows), copy mode, and PowerShell for sound and notifications. Agents and the skill should work; guardrails and alerts may need adjustments. |

## Limitations

- Agent prompts are in Portuguese (outputs follow your language).
- One squad per user install (`~/.claude`); `CLAUDE_CONFIG_DIR` pointing elsewhere is not supported yet.
- Measured on small demands so far; see [docs/case-study.md](docs/case-study.md).

## Repository layout

```
squadgate/
├── install.sh · uninstall.sh · hooks.json
├── agents/                 Analyst, UX, Architect, Developer, QA
├── skills/squad/SKILL.md   Orchestrator and /squad commands
├── bin/                    squad-estado, squad-painel, squad-hook
├── lib/squad.py            state, guardrails, panel, cost, alerts
├── lib/settings_hooks.py   adds/removes hooks in settings.json
├── painel/template.html    live panel
└── docs/case-study.md      what was measured and what changed
```

## License

[MIT](LICENSE)
