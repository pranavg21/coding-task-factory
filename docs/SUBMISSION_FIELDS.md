# Submission fields (Hack2skill prototype form)

Update both texts if the live runs change what the factory does. Limit: 1,024 characters each.

## Prototype Brief (982 characters)

A reusable Coding Task Factory: point it at a repository and it produces SWE-bench-style task packages (new features, feature changes, bug fixes), each proven by executed tests. It runs on all three supplied repositories: click (pytest), zod (Vitest with type checks) and jsoncpp (C++). Gemini agents plan structurally different changes and reject near-duplicates; a spec writer fixes an exact interface contract; one agent writes the reference patch while another writes tests without seeing it. Every package must pass the organisers' three conditions, judged test by test on 3 fresh copies; flaky tests and test tampering reject it. Planted bugs must fail the tests, and a blind agent given only the spec must solve the task. Every model call is recorded, so a replayed run rebuilds identical packages with no API calls. Packages ship task.toml, instruction.md, solution/patch.diff, tests/run_tests.sh, test cases and evidence; a report shows the funnel, variety and catch rates.

## Technology Stack (888 characters)

Python 3.11+ (Pydantic schemas, Typer command line), dependencies pinned in constraints.txt. AI: Gemini via Google AI Studio (google-genai SDK) in our own tool loop that records every request and response for exact replay; Claude is supported as an alternative provider. Test stacks: pytest for click, Vitest with TypeScript type checks for zod, CMake + Ninja with jsoncpp's own jsontest framework for jsoncpp. Isolation: a fresh copy of the repository per agent and per run, git history removed; optional Docker with --network=none. Task format: SWE-bench conventions (task.toml, instruction.md, solution/patch.diff, tests/run_tests.sh, FAIL_TO_PASS and PASS_TO_PASS lists). Evidence: proof.json, strength.json and compressed logs per task, funnel.json, static HTML audit report. Quality: GitHub Actions CI and 42 factory tests, including end-to-end generation and byte-identical replay.
