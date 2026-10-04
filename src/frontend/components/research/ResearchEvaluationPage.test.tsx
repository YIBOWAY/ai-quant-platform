import { describe, it, expect, vi } from "vitest";
import Page from "@/app/research-evaluation/page";
vi.mock("@/lib/serverLocale", () => ({ getServerLocale: async () => "zh" }));

describe("research evaluation route identity", () => {
  it.each(["research:strategy-" + "a".repeat(24), "research:artifact-abc"])("preserves %s", async key => {
    const page = await Page({ searchParams: Promise.resolve({ key, tab: "rolling" }) });
    expect(page.props.children.props.researchKey).toBe(key);
  });
  it.each(["research:strategy-invalid", "research:strategy-" + "a".repeat(25), "../../record", ["research:artifact-abc"]])("rejects malformed %s", async key => {
    const page = await Page({ searchParams: Promise.resolve({ key }) });
    expect(page.props.children.props.researchKey).toBeNull();
  });
});
