import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

describe("frontend OpenAPI type ownership", () => {
  it("derives candidate detail from the generated required-field contract", () => {
    const source = readFileSync(path.join(process.cwd(), "lib/api.ts"), "utf8");
    const declaration = source.slice(
      source.indexOf("export type AgentCandidateDetailResponse"),
      source.indexOf("export type AgentTaskResponse"),
    );

    expect(declaration).toContain(
      'HermesSchemas["AgentCandidateDetailResponse"]',
    );
    expect(declaration).not.toContain("integrity_state?:");
    expect(declaration).not.toContain("approval_enabled?:");
    expect(declaration).not.toContain("status?:");
  });
});
