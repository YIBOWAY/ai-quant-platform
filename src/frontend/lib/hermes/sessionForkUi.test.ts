import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import {
  canSubmitSessionFork,
  HermesSessionForkController,
  HermesSessionForkPolicyConfirmation,
} from "@/components/hermes/sessions/HermesSessionForkController";
import { PROVIDER_POLICY_DIGEST } from "@/lib/hermes/darkIdentity";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

const messages = [
  {
    id: "upstream-display-1",
    role: "user",
    content: "Keep this exact context",
    timestamp: "2026-07-24T08:00:00Z",
    fork_point: "message:42",
  },
  {
    id: "synthetic-display-2",
    role: "assistant",
    content: "This row has no authoritative upstream cursor",
    timestamp: "2026-07-24T08:00:01Z",
    fork_point: null,
  },
];

describe("HermesSessionForkController", () => {
  it("requires an explicit immutable openai / gpt-5 policy confirmation", () => {
    expect(
      canSubmitSessionFork({
        busy: false,
        policyConfirmed: false,
        selectedForkPoint: "message:42",
      }),
    ).toBe(false);
    expect(
      canSubmitSessionFork({
        busy: false,
        policyConfirmed: true,
        selectedForkPoint: "message:42",
      }),
    ).toBe(true);

    const html = renderToStaticMarkup(
      createElement(HermesSessionForkPolicyConfirmation, {
        checked: false,
        disabled: false,
        isZh: false,
        onChange: vi.fn(),
      }),
    );
    expect(html).toContain('type="checkbox"');
    expect(html).toContain("min-h-11");
    expect(html).toContain("openai / gpt-5");
    expect(html).toContain(PROVIDER_POLICY_DIGEST);
    expect(html).toContain("data-hermes-session-fork-policy-confirmation");
  });

  it("shows one accessible 44px action only for an eligible authoritative message", () => {
    const html = renderToStaticMarkup(
      createElement(HermesSessionForkController, {
        forkEligible: true,
        hermesSessionId: "agent:main:discord",
        isZh: false,
        messages,
      }),
    );

    expect(html.match(/data-hermes-message-fork-select/g)).toHaveLength(1);
    expect(html).toContain("Continue from here");
    expect(html).toContain("min-h-11");
    expect(html).toContain('aria-pressed="false"');
    expect(html).toContain('data-hermes-fork-point="message:42"');
    expect(html).not.toContain('data-hermes-fork-point="message:2"');
    expect(html).not.toContain("data-hermes-session-fork-confirm-action");
  });

  it("keeps all fork actions absent when the detail contract is ineligible", () => {
    const html = renderToStaticMarkup(
      createElement(HermesSessionForkController, {
        forkEligible: false,
        forkReasonCode: "source_session_not_external",
        hermesSessionId: "web_managed",
        isZh: true,
        messages,
      }),
    );

    expect(html).not.toContain("data-hermes-message-fork-select");
    expect(html).not.toContain("从这里继续");
    expect(html).toContain("此会话不能创建分支");
  });
});
