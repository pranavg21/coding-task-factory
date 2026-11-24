# Gold tasks (hand-built calibration references)

One task per supplied repository, written by the team, not by the factory. They exist to:

1. prove the harness, adapters and 3-condition proof work on the real repositories before any AI
   generation is trusted, and
2. give the generation stage a concrete example of the target quality.

They go through exactly the same pipeline as generated tasks (`scripts/build_gold_task.py`), but they are
**not counted as factory output** in any metric, and they are listed separately in the report.

| Task | Repository (pinned) | Change | New tests |
|---|---|---|---|
| `click-duration` | pallets/click `08b803c` | `click.Duration` parameter type | 18 |
| `zod-array-unique` | colinhacks/zod `d40c329` | `.unique()` on array schemas | 10 |
| `jsoncpp-flatten` | open-source-parsers/jsoncpp `93acc7b` | `Json::Value::flatten()` | 6 |

Each folder holds `instruction.md`, `solution.patch`, `cases/` (new test files laid out as they belong
in the repository) and `gold.json` (metadata and the pinned commit).
