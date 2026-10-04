import assert from "node:assert/strict";
import { test } from "node:test";
import { selectE2EArguments } from "./e2e-selection.mjs";

test("repeat options retain the production-only selector, in both CLI forms", () => {
  assert.deepEqual(selectE2EArguments("prefetch", ["--repeat-each=3"]), ["--grep=@production-prefetch", "--repeat-each=3"]);
  assert.deepEqual(selectE2EArguments("prefetch", ["--repeat-each", "3"]), ["--grep=@production-prefetch", "--repeat-each", "3"]);
});
test("explicit spec or grep intentionally replaces the mode selector", () => {
  for (const args of [["tests/e2e/hermes-production-prefetch.spec.ts", "--repeat-each=3"], ["--grep=precise case"], ["--grep-invert=excluded"], ["--grep", "precise case"]]) {
    assert.deepEqual(selectE2EArguments("prefetch", args), args);
  }
});
test("real and brief batches partition the independently isolated visual cases", () => {
  const [real] = selectE2EArguments("real", ["--repeat-each=2"]);
  assert.match(real, /@brief-visual/); assert.match(real, /@production-prefetch/);
  assert.deepEqual(selectE2EArguments("brief"), ["--grep=@brief-visual"]);
});
test("invalid modes fail before any process or network action", () => {
  assert.throws(() => selectE2EArguments("formal"), /Unknown isolated E2E mode/);
});
