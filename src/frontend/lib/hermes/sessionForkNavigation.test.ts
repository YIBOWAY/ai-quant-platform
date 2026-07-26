import { describe, expect, it, vi } from "vitest";

import {
  activateReadyHermesFork,
  activateReadyManagedHermesSession,
} from "./sessionForkNavigation";

describe("activateReadyHermesFork", () => {
  it("binds and navigates transcript/composer to the same ready child session", () => {
    const bindHermesSession = vi.fn();
    const navigate = vi.fn();
    const childId = "web_" + "a".repeat(40);

    const href = activateReadyHermesFork({
      hermesSessionId: childId,
      locale: "zh",
      bindHermesSession,
      navigate,
    });

    expect(bindHermesSession).toHaveBeenCalledWith(childId);
    expect(navigate).toHaveBeenCalledWith(
      `/zh/hermes?hermes_session_id=${childId}`,
    );
    expect(href).toBe(`/zh/hermes?hermes_session_id=${childId}`);
  });

  it("uses the same canonical handoff for a fresh root managed session", () => {
    const bindHermesSession = vi.fn();
    const navigate = vi.fn();
    const sessionId = "web_" + "b".repeat(40);

    const href = activateReadyManagedHermesSession({
      hermesSessionId: sessionId,
      locale: "en",
      bindHermesSession,
      navigate,
    });

    expect(bindHermesSession).toHaveBeenCalledWith(sessionId);
    expect(navigate).toHaveBeenCalledWith(
      `/en/hermes?hermes_session_id=${sessionId}`,
    );
    expect(href).toBe(`/en/hermes?hermes_session_id=${sessionId}`);
  });
});
