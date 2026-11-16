# Case study: building and measuring squadgate

squadgate was built as a proof of concept and validated on a small sample Python project (standard library only, a handful of unit tests) before being used on real work. This page records what was tested, what was measured and what changed as a result.

## Goal

A previous multi-agent setup, where one agent acted as orchestrator, had three problems: it spent a lot, it seemed to loop, and long tasks ran with no visibility. squadgate set out to fix exactly those:

| Problem | Answer in squadgate |
|---|---|
| Unclear cost | Orchestrator on a cheaper model, agents with defined models and effort, `/squad cost` to measure every demand |
| Loops | Hard limits: 3 attempts per block, same failure twice stops, 2 review rounds, `maxTurns` per agent |
| No visibility | Gates you approve, a status line at every handoff, a local live panel and system alerts |

## Test 1: a trap demand

The demand asked for a plugin system for per-client calculation rules, configured by YAML, with a repository layer and an in-memory cache. In the sample project, the function already took the rates as parameters, there was no client with different rules, and YAML would need an external dependency the project forbids.

- **Passed:** the Analyst challenged the premise before any code was written, cited the exact line where the parameters already existed, and proposed shrinking the demand from L to S.
- **Escaped:** at Gate 0, the Orchestrator offered the user a technical choice (YAML with a dependency, or a hand-written parser). A format the standard library already reads was simpler.
- **Changed:** the Orchestrator may not offer technical options; conflicts become questions for the Analyst and the Architect. The Architect must check inherited technical decisions for a simpler path.

## Test 2: a medium demand

A business rule added to an existing calculation.

- **Delivery:** correct, in about 12 minutes. The Analyst suggested reducing the size, the Developer passed on the first attempt and the review approved on the first round.
- **Cost:** the Orchestrator consumed **about 86% of all tokens**; the four agents together, about 14%.
- **Root cause:** agents ran in the background. When a background agent finishes, its result opens a new turn, and that turn runs on the session's default model (a larger one) instead of the model the `/squad` skill asked for. Each model switch also rewrote the prompt cache. The agents' own `background: false` setting did not change this: only an explicit `run_in_background: false` on each call does.
- **Also found:** the demand ran in a conversation that already carried the previous test, so every Orchestrator step re-read that history.

## Test 3: an ambiguous demand

Show the customer a breakdown of the amount due: original value, fee, interest and total.

- **Quality, best so far:** the Analyst caught the real trap. If each part is rounded on its own, the parts may not add up to the total. It stopped with a blocking question and a numeric example; the user chose "total = sum of the rounded parts". Tests, implementation, review and validation all passed on the first try (10 criteria).
- **Cost, no better:** the first agent call passed `run_in_background` as the text `"false"`, the hook only accepted the boolean, and its message suggested retrying without the parameter. The Orchestrator then dropped it on every call, and stayed on the larger model for 38 of 44 calls (76% of the tokens).
- **Changed:** the hook accepts `false` and `"false"`, and its message always asks to retry with the parameter.

## What the measurements changed

| Finding | Change |
|---|---|
| Orchestrator re-typed the agents' output | Each agent writes its own file and returns a 20-line summary |
| Background agents switched the session model | Skill rule plus a hook that blocks squad agents launched without `run_in_background: false` |
| Old conversation history carried into the demand | Gate 0 recommends a fresh session when the conversation already has history |
| No per-demand cost view | `/squad cost`, reading local transcripts at no quota cost |
| Same effort for every task | Effort chosen per task and size (one table in the skill) |
| User missed long-running steps | Sound and system notification when an agent finishes and when a gate waits |

## Open points

- The foreground fix was verified in the hook, but not yet in a full demand.
- Reasoning effort passed per call is not recorded in the transcripts, so it cannot be verified from `/squad cost`.
- Windows support is untested.
