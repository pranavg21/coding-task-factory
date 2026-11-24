# Coding Task Factory — Innodata AI Hackathon (Track 1)

A reusable, CLI-driven **Coding Task Factory** that ingests any software repository (Git URL or ZIP), plans structurally diverse net-new features and verified bug fixes, generates isolated specs, patches, and tests, and accepts **only** tasks that pass deterministic verification inside an offline Docker sandbox.

> **Core Engineering Rule:** AI agents propose and write; only executed tests inside isolated containers decide what ships.

## Status (what exists and what has been proven)

| Part | State | Evidence |
|---|---|---|
| 3-condition proof, per test, 3 fresh runs, flake rejection | Built and proven on all 3 supplied repositories | `samples/gold/*/evidence/` |
| Test adapters: pytest (click), Vitest (zod), jsontest (jsoncpp) | Built and proven | `factory/adapters/harness.py`, gold tasks |
| Baseline discovery (only tests passing 3 untouched runs enter PASS_TO_PASS) | Built and proven | `factory/onboarding/baseline.py` |
| Patch guard (no edits, deletes, renames or hiding of existing tests) | Built, tested | `tests/test_patch_guard_bypasses.py` |
| Test strength (planted bugs must fail the new tests; survivors listed) | Built and measured on gold tasks: 15 of 17 caught | `samples/gold/*/evidence/strength.json` |
| AI generation (Gemini): planner, spec writer, Agent A, Agent B (patch-blind), judge | Built and tested end to end with scripted Gemini and Claude responses; **not yet run against the live API** | `factory/agents/`, `tests/test_gemini.py`, `tests/test_generate.py` |
| Blind solve: an agent with only `instruction.md` must pass the tests, or the failure must be judged the agent's; sets difficulty | Built, tested | `factory/verifier/blind_solve.py` |
| Record/replay of every model call (replayed runs write byte-identical packages) | Built, tested | `factory/agents/llm.py`, `tests/test_generate.py` |
| Audit report built only from output folders | Built | `report/index.html` |
| Docker execution | Command built; **untested** (no Docker where this was developed). Local execution is the tested path | `factory/verifier/proof_runner.py` |

Gold tasks (hand-built references, not counted as factory output):

| Task | New tests | Existing tests | Conditions 1-3, 3 runs | Planted bugs caught |
|---|---|---|---|---|
| click: `click.Duration` parameter type | 18 | 2,628 | passed, 0 flaky | 7/8 (survivor is behaviour-neutral: click falls back to the same metavar) |
| zod: `.unique()` on array schemas | 10 | 5,545 | passed, 0 flaky | 2/3 (survivor shows a real gap: no test for arrays containing `undefined`) |
| jsoncpp: `Json::Value::flatten()` | 6 | 133 | passed, 0 flaky | 6/6 |

## Generating tasks (Gemini via Google AI Studio)

```bash
bash environments/setup.sh click /work/click                     # pinned checkout + dependencies
export GEMINI_API_KEY=...                                          # Google AI Studio key
factory models                                                     # models this key can use
export GEMINI_MODEL=<model id>                                     # e.g. the strongest Pro model listed
factory generate --repo click --checkout /work/click --n 15 --seed 42 \
    --python /work/click/.venv/bin/python --mode record            # saves every model response
factory generate --repo click --checkout /work/click --n 15 --seed 42 \
    --python /work/click/.venv/bin/python --mode replay            # no API calls; identical packages
factory report --outputs outputs --out report/index.html
```

Behind a proxy that adds the `x-goog-api-key` header itself, set `GEMINI_KEY_VIA_PROXY=1` instead of
`GEMINI_API_KEY`. Set `FACTORY_PRICE_IN` / `FACTORY_PRICE_OUT` (USD per million tokens, from Google's price
list for your model) to see dollar costs; otherwise the report shows token counts only.

The agents call Gemini through the `google-genai` SDK with a tool loop the factory runs itself
(`factory/agents/loop.py`), so every request can be recorded and replayed. Gemini's thought signatures
are kept and sent back unchanged on each turn. Rate limits (HTTP 429) are retried after the delay Google
suggests. The same roles also run on Claude (`--provider anthropic`), which the tests exercise too.

Each agent works in its own copy of the repository: the implementer can only change source files; the
test writer can only create new test files and never sees the implementer's copy; the blind solver gets
only `instruction.md`.

## Quickstart

```bash
pip install -e ".[dev]" -c constraints.txt
pytest -q
factory --help          # generate, prove, models, report
```

## Proving a task package (the organisers' 3-condition matrix)

```bash
factory prove --task outputs/<repo_id>/<task_id> --repo <base checkout>            # local
factory prove --task outputs/<repo_id>/<task_id> --repo <base checkout> --image <docker image>  # offline container
```

Each of 3 runs uses a fresh copy of the base repository with git history removed:

| Condition | Repository | Tests | Must |
|---|---|---|---|
| 1. Baseline Pass | untouched (nothing copied in) | `PASS_TO_PASS` | every test passes |
| 2. Solution Pass | `solution/patch.diff` applied | `PASS_TO_PASS` + `FAIL_TO_PASS` | every test passes |
| 3. Feature Failure Verification | untouched + new tests | `FAIL_TO_PASS` | every test fails |

Every test is judged by its own result, not the overall exit code, and a test that did not run counts
as not passing. A test whose result differs between runs is counted as flaky, and the task is rejected.
Logs for all 9 executions are written to `evidence/logs/` (gzip-compressed). Each package also ships
`tests/run_tests.sh <repo_dir> <pass_to_pass|fail_to_pass|all>` so anyone can rerun a condition by hand.

Set `SOURCE_DATE_EPOCH` to fix the `created_at` timestamp so a replayed run writes identical packages.

## Supplied repositories and environments

| Repository | Pinned commit | Stack | Test adapter | Existing tests in PASS_TO_PASS |
|---|---|---|---|---|
| pallets/click | `08b803c` | Python | pytest (`PYTHONPATH` puts the checkout's `src/` first) | 2,628 |
| colinhacks/zod | `d40c329` | TypeScript | Vitest project `zod`, JSON reporter, includes type checks | 5,545 |
| open-source-parsers/jsoncpp | `93acc7b` | C++ (CMake + Ninja) | jsoncpp's own `jsontest`, one test at a time by name | 133 |

`bash environments/setup.sh <click|zod|jsoncpp> <dir>` recreates each repository at its pinned commit with
dependencies installed. Counts are tests that passed on 3 consecutive untouched runs; any test that did not
is excluded from PASS_TO_PASS and listed in each task's `evidence/proof.json`.

**Environment notes (disclosed, not manual edits to outputs):** Zod is built with the Nub package manager,
which is not on npm. Its lockfile is in pnpm format, so the setup installs with pnpm after adding a
`pnpm-workspace.yaml` and turning off pnpm's package-manager check. Neither step changes Zod's code or tests.
For jsoncpp, a task's new tests are compiled as a separate test program against the built library, so
jsoncpp's own build files are never edited.

## Public starter repositories (used before the supplied repositories were announced)

Develop against three diverse stacks right away so zero logic is hardcoded before the 3 official Innodata repos arrive:

1. **Python Web Shop / API:** FastAPI or Flask e-commerce / CRUD backend with `pytest` (mirrors Innodata's voucher/discount example).
2. **TypeScript / Express API:** Node.js + TypeScript REST service with `Vitest` or `Jest`.
3. **Python CLI / Library:** Pure Python data/utility package with strong unit test layout (plus 1 unseen **held-out** public repo reserved for Dec 2–3 generality testing).

## 4-Person Team Split

| Owner | Modules Owned |
| :--- | :--- |
| **Person A (Env & Checks)** | `factory/sandbox/`, `factory/adapters/` (`python_pytest`, `js_vitest_jest`), `factory/verifier/proof_runner.py` |
| **Person B (Generation)** | `factory/agents/contracts.py`, Variety Planner, Spec Writer, Agent A (Coder), Agent B (Blind Test Writer), revision loop |
| **Person C (Test Strength & Guards)** | `factory/verifier/diff_mutator.py`, Adversary patches, Blind Solver, `factory/sandbox/patch_guard.py`, safety filter |
| **Person D (Evidence & Story)** | `factory/verifier/variety_scorer.py`, `factory/adapters/swebench_packager.py`, `factory/reporting/html_report.py`, docs, PPT, demo |

## Locked Output Package Schema

Every accepted task is exported under `outputs/<repo_id>/<task_id>/`:

```text
<task_id>/
├── task.toml               # Repo source, pinned SHA/hash, stack, test commands
├── instruction.md          # Requirement + Acceptance Criteria + ## Interface Contract
├── solution/
│   └── patch.diff          # Reference implementation diff (never touches existing tests)
├── tests/                  # Blind-authored feature tests
├── metadata.json           # Variety cell, scores, provenance, cost/runtime
└── evidence/
    ├── proof.json          # 3-step proof (3x reruns), FAIL_TO_PASS, PASS_TO_PASS, kill rate
    └── logs/               # Raw stdout/stderr per verification run
```
