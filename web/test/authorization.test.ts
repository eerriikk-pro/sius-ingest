import assert from "node:assert/strict";
import test from "node:test";

import { mayQueryMemberNumber } from "../lib/authorization.ts";

test("a regular user may query every approved member number", () => {
  assert.equal(mayQueryMemberNumber("user", ["101", "202"], "101"), true);
  assert.equal(mayQueryMemberNumber("user", ["101", "202"], "202"), true);
});

test("a regular user may not query an unapproved member number", () => {
  assert.equal(mayQueryMemberNumber("user", ["101", "202"], "303"), false);
  assert.equal(mayQueryMemberNumber("user", [], "101"), false);
});

test("an administrator may query any valid member number", () => {
  assert.equal(mayQueryMemberNumber("admin", [], "303"), true);
});
