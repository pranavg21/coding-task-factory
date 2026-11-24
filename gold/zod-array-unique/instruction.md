## Problem Statement
Zod array schemas can constrain length (`.min()`, `.max()`, `.length()`, `.nonempty()`) but cannot require that items are distinct, so users write the same `superRefine` by hand for tags, IDs or selections. Add a `.unique()` method to array schemas that rejects arrays containing the same element more than once.

## Acceptance Criteria
1. `z.array(schema).unique()` accepts arrays whose elements are all distinct, including the empty array, and returns the parsed array unchanged.
2. If an element repeats, parsing fails with exactly one issue, reported at the first repeated element: `code` is `"custom"`, `path` is `[index]` (the index of the second occurrence of the first value that repeats), and `message` is `"Array items must be unique"`.
3. `.unique(message)` uses the given string as the issue message instead.
4. Elements are compared with `Set` semantics (SameValueZero): `NaN` equals `NaN`, and objects are equal only if they are the same reference, so two separate objects with equal contents are allowed.
5. `.unique()` returns the same array schema type, so it chains with the other array checks (for example `.min(2).unique()`) and the inferred type is unchanged (`string[]` for `z.array(z.string())`).

## Interface Contract
- **File:** `packages/zod/src/v4/classic/schemas.ts`, on the classic `ZodArray` (the `zod/v4` import).
- **Type declaration** (in `interface ZodArray`): `unique(message?: string): this;`
- **Behaviour on failure:** one issue `{ code: "custom", path: [index], message }`; parsing does not continue looking for further duplicates.

## Non-Goals & Constraints
- No deep (structural) equality and no key selector.
- Zod Mini and Zod 3 are out of scope.
- Do not change existing array checks or modify existing tests.
