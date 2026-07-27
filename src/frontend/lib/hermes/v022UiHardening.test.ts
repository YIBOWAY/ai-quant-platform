import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TodayResults } from "@/components/hermes/today";

const api = vi.hoisted(() => ({
  getHermesSessionDetail: vi.fn(),
  getHermesSessionMessages: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api")>();
  return { ...original, ...api };
});

vi.mock("@/lib/serverLocale", () => ({
  getServerLocale: vi.fn(async () => "en" as const),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

import HermesSessionDetailPage from "@/app/hermes/sessions/[sessionId]/page";

describe("v0.2.2 Hermes UI hardening", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the unified-results navigation as a 44px touch target", () => {
    const html = renderToStaticMarkup(
      createElement(TodayResults, {
        preview: {
          readStatus: "empty",
          total: 0,
          items: [],
        },
        hqaConclusions: [],
        locale: "en",
      }),
    );

    expect(html).toMatch(
      /<a class="[^"]*app-touch-target[^"]*min-h-\[44px\][^"]*" href="\/en\/hermes\/results">View all →<\/a>/,
    );
    expect(html).toContain("-my-[13px]");
  });

  it("fails closed when an older persisted-session response omits fork_context", async () => {
    api.getHermesSessionDetail.mockResolvedValue({
      read_status: "available",
      session: {
        id: "fixture-long-session",
        title: "Fixture long session",
        source: "discord",
      },
      warnings: [],
    });
    api.getHermesSessionMessages.mockResolvedValue({
      read_status: "available",
      session_id: "fixture-long-session",
      messages: [
        {
          id: "fixture-message-1",
          role: "user",
          content: "Historical fixture message",
          fork_point: "message:1",
        },
      ],
      omitted_message_count: 0,
      warnings: [],
    });

    const page = await HermesSessionDetailPage({
      params: Promise.resolve({ sessionId: "fixture-long-session" }),
    });
    const html = renderToStaticMarkup(createElement(() => page));

    expect(html).not.toContain("Continue from here");
    expect(html).not.toContain("data-hermes-message-fork-select");
    expect(html).toContain("fork_context_unavailable");
  });
});
