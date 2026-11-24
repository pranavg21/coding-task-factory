## Problem Statement
Command-line tools often take time spans such as a timeout or a retry interval. Click has no parameter type for this, so every application parses strings like `90s` or `1h30m` itself. Add a `Duration` parameter type that converts such strings into `datetime.timedelta`.

## Acceptance Criteria
1. `click.Duration()` converts a duration string to a `datetime.timedelta`. A duration is one or more `<integer><unit>` parts with no spaces, using units `d` (days), `h` (hours), `m` (minutes) and `s` (seconds). Examples: `90s`, `15m`, `1h30m`, `2d`, `1d2h3m4s`.
2. Each unit may appear at most once and units must appear in the order `d`, `h`, `m`, `s` (`30m1h` and `1h1h` are invalid). Units are case-insensitive (`2H` is two hours).
3. A string of digits only (for example `45`) is a number of seconds.
4. Any other input (empty string, unknown unit, decimals such as `1.5h`, negative values, or spaces between parts) fails with the message `'<value>' is not a valid duration.` and exit code 2 when used on the command line.
5. A `datetime.timedelta` value is returned unchanged; a non-negative `int` is a number of seconds.
6. Optional keyword arguments `min` and `max` (each a `timedelta` or `None`) bound the result. Values below `min` fail with a message containing `is shorter than the minimum`; values above `max` fail with a message containing `is longer than the maximum`. The bounds are inclusive.
7. The type's `name` is `"duration"`, and help output shows its metavar as `DURATION` (for example `--wait DURATION`).

## Interface Contract
- **Module:** `src/click/types.py`; also exported from the package as `click.Duration`.
- **Class:** `class Duration(ParamType[datetime.timedelta])`
- **Constructor:** `Duration(min: timedelta | None = None, max: timedelta | None = None)`
- **Method:** `convert(value, param, ctx) -> datetime.timedelta`, reporting errors through `self.fail(...)` like the other Click types.
- **Attributes:** `name = "duration"`; `get_metavar(param, ctx)` returns `"DURATION"`.

## Non-Goals & Constraints
- No floating-point amounts, weeks, months or years.
- Do not change existing parameter types or modify existing tests.
