# Changelog

All notable changes to squadgate. Versions follow [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-11-16

First usable version.

### Added
- `/squad` orchestrator with four agents (Analyst, Architect, Developer, QA) and approval gates 0 to 3.
- Sizes S/M/L that choose the flow; `--step-by-step` mode.
- Guardrails enforced by hooks while a demand is active: commit pattern, protected branches, forced push, destructive and production commands.
- Foreground rule for squad agents, enforced by a hook.
- Reasoning effort per task and size.
- Local live panel with gates, team, ETA, activity, a commands drawer and a PT / EN switch.
- `/squad cost`: tokens per agent and model from local transcripts.
- Sound and system notifications on macOS, Linux and Windows (Windows untested).
- Automatic language: the squad writes in the language of the demand; commits follow the project's language.
- `install.sh` and `uninstall.sh` that keep other settings and back up anything they replace.
