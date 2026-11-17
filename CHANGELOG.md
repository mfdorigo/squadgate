# Changelog

All notable changes to squadgate. Versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- UX role (`squad-ux`): when the story touches a screen, it sketches it in `telas.md` before Gate 1, and on request builds a clickable prototype (`prototipo.html`) for discussion. Shows in the panel as "UX".
- The panel shows every running agent, not only squad roles. An agent outside the squad shows with a dashed warning border.

### Changed
- The orchestrator calls only squad roles. Any other agent (general-purpose, Explore, Plan, fork) needs the user's permission first, with a note that the squad may need adjusting.
- The Analyst's summary says whether the story touches a screen.

## [0.2.0] - 2026-11-17

### Changed
- The PT / EN switch now changes the whole panel. The orchestrator writes every free text in `painel.json` in Portuguese and English (`{"pt": ..., "en": ...}`), and the panel names steps E0–E6 and roles itself. Older `painel.json` files with plain strings still show as written.
- The panel page refreshes itself after squadgate is updated, instead of keeping the old page until `/squad panel` runs again.

### Added
- First automated tests (`tests/`): panel rendering in both languages and the panel data generation.

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
