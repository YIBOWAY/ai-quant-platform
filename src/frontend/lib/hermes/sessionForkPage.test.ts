import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

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

describe("Hermes session detail fork wiring", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getHermesSessionDetail.mockResolvedValue({
      read_status: "available",
      session: {
        id: "agent:main:discord",
        title: "Discord research",
        source: "discord",
      },
      fork_context: {
        eligible: true,
        source_channel: "discord",
        reason_code: null,
      },
      warnings: [],
    });
    api.getHermesSessionMessages.mockResolvedValue({
      read_status: "available",
      session_id: "agent:main:discord",
      messages: [
        {
          id: "display-id-is-not-the-cursor",
          role: "user",
          content: "Continue this discussion",
          fork_point: "message:77",
        },
      ],
      omitted_message_count: 0,
      warnings: [],
    });
  });

  it("wires backend eligibility and the exact message cursor into the selector", async () => {
    const page = await HermesSessionDetailPage({
      params: Promise.resolve({ sessionId: "agent:main:discord" }),
    });
    const html = renderToStaticMarkup(createElement(() => page));

    expect(html).toContain("Continue from here");
    expect(html).toContain("data-hermes-session-deep-link");
    expect(html).toContain('data-hermes-session-id="agent:main:discord"');
    expect(html).toContain('data-hermes-fork-point="message:77"');
    expect(html).not.toContain(
      'data-hermes-fork-point="message:display-id-is-not-the-cursor"',
    );
  });

  it("does not infer eligibility from the session source or a message id", async () => {
    api.getHermesSessionDetail.mockResolvedValue({
      read_status: "available",
      session: {
        id: "agent:main:discord",
        title: "Discord research",
        source: "discord",
      },
      fork_context: {
        eligible: false,
        source_channel: null,
        reason_code: "source_session_not_external",
      },
      warnings: [],
    });

    const page = await HermesSessionDetailPage({
      params: Promise.resolve({ sessionId: "agent:main:discord" }),
    });
    const html = renderToStaticMarkup(createElement(() => page));

    expect(html).not.toContain("Continue from here");
    expect(html).not.toContain("data-hermes-message-fork-select");
    expect(html).toContain("This session cannot be forked");
  });
});
