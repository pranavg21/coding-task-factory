## Problem Statement
Applications that log, diff or store JSON configuration often need it as flat key/value pairs (`server.port = 8080`). jsoncpp has no way to do this, so callers write their own recursive walk. Add a `flatten` method to `Json::Value` that returns an object mapping each leaf's path to the leaf's value.

## Acceptance Criteria
1. `value.flatten()` returns a new `Json::Value` of type `objectValue`. Each member key is the path to a leaf: object keys and array indexes (in decimal) along the way, joined with `.`. Example: `{"a":{"b":[1,2]},"c":"x"}` becomes `{"a.b.0":1,"a.b.1":2,"c":"x"}`.
2. `value.flatten(sep)` joins path parts with the character `sep` instead of `.`.
3. Leaves are scalars (including `null`) and **empty** objects or arrays. An empty container is kept as an empty container of the same type at its path; a non-empty container never appears as a value.
4. If the value itself is a scalar (not an object or array), the result has exactly one member, with key `""` (empty string), holding a copy of the value.
5. Arrays at the root work the same way: `[[true],{"k":"v"}]` becomes `{"0.0":true,"1.k":"v"}`.
6. The original value is not modified.

## Interface Contract
- **Declaration:** in `include/json/value.h`, inside `class Value`: `Value flatten(char separator = '.') const;`
- **Definition:** in `src/lib_json/json_value.cpp`.
- **Return type:** `Json::Value` of type `objectValue`; leaf values are copies.

## Non-Goals & Constraints
- No escaping of separator characters that appear inside keys, and no inverse "unflatten".
- Do not change existing behaviour or modify existing tests.
