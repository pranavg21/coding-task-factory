import { expect, expectTypeOf, test } from "vitest";
import * as z from "zod/v4";

test("accepts arrays without repeated elements", () => {
  const schema = z.array(z.number()).unique();
  expect(schema.parse([1, 2, 3])).toEqual([1, 2, 3]);
  expect(schema.parse([])).toEqual([]);
});

test("rejects the first repeated element with a custom issue at its index", () => {
  const result = z.array(z.string()).unique().safeParse(["a", "b", "a", "b"]);
  expect(result.success).toBe(false);
  if (!result.success) {
    expect(result.error.issues).toHaveLength(1);
    const [issue] = result.error.issues;
    expect(issue.code).toBe("custom");
    expect(issue.path).toEqual([2]);
    expect(issue.message).toBe("Array items must be unique");
  }
});

test("uses a custom message when given", () => {
  const result = z.array(z.number()).unique("No duplicate ids").safeParse([7, 7]);
  expect(result.success).toBe(false);
  if (!result.success) expect(result.error.issues[0].message).toBe("No duplicate ids");
});

test("compares like a Set: NaN equals NaN, objects by reference", () => {
  const schema = z.array(z.any()).unique();
  expect(schema.safeParse([Number.NaN, Number.NaN]).success).toBe(false);
  const obj = { id: 1 };
  expect(schema.safeParse([obj, obj]).success).toBe(false);
  expect(schema.safeParse([{ id: 1 }, { id: 1 }]).success).toBe(true);
});

test("chains with other array checks and keeps the inferred type", () => {
  const schema = z.array(z.string()).min(2).unique();
  expectTypeOf<z.infer<typeof schema>>().toEqualTypeOf<string[]>();
  expect(schema.safeParse(["x"]).success).toBe(false);
  expect(schema.safeParse(["x", "y"]).success).toBe(true);
});
