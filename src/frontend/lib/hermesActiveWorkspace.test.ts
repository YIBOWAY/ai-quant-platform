import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { HermesLocalChatBoundary } from "@/components/hermes/shell/HermesLocalChatBoundary";

const composer = {
  label: "Talk with Hermes",
  placeholder: "locked",
  placeholderOpen: "open",
  sendEnabled: "Send",
  sendDisabled: "Send (disabled)",
  unavailable: "unavailable",
};

describe("UI-2 Direction A active-state two-column workspace", () => {
  it("places transcript in the main column and the four context panels in rail order", () => {
    const html = renderToStaticMarkup(
      createElement(HermesLocalChatBoundary, {
        chatOpen: true,
        composer,
        deliveryState: "local_mutation_authorized" as const,
        locale: "zh" as const,
      },
      createElement("div", { "data-today-children": true }),
      ),
    );

    // Layout containers exist with the two-column grid + rail markers.
    expect(html).toContain('data-hermes-active-grid="true"');
    expect(html).toContain("min-[1100px]:grid-cols-[minmax(0,1fr)_320px]");
    expect(html).toContain('data-hermes-active-main="true"');
    expect(html).toContain('data-hermes-active-rail="true"');
    expect(html).toContain("min-[1100px]:sticky");

    // Rail order: approvals → activity → typed results → gates → authority.
    const transcript = html.indexOf("data-hermes-token-stream");
    const approvals = html.indexOf("data-hermes-command-approvals");
    const activity = html.indexOf("data-hermes-command-activity");
    const typedResults = html.indexOf("data-hermes-typed-results-observe");
    const gates = html.indexOf("data-hermes-gate-observe");
    const authority = html.indexOf("data-hermes-authority-observe");
    const todayChildren = html.indexOf("data-today-children");

    for (const marker of [transcript, approvals, activity, typedResults, gates, authority]) {
      expect(marker).toBeGreaterThan(-1);
    }
    expect(transcript).toBeLessThan(approvals);
    expect(approvals).toBeLessThan(activity);
    expect(activity).toBeLessThan(typedResults);
    expect(typedResults).toBeLessThan(gates);
    expect(gates).toBeLessThan(authority);
    // Today content (UI-1) stays below the panel workspace.
    expect(todayChildren).toBeGreaterThan(authority);
  });

  it("chat closed renders no workspace grid (server-only locked path)", () => {
    const html = renderToStaticMarkup(
      createElement(HermesLocalChatBoundary, {
        chatOpen: false,
        composer,
        deliveryState: "blocked_in_this_slice" as const,
        locale: "zh" as const,
      },
      createElement("div", null),
      ),
    );
    expect(html).not.toContain("data-hermes-active-grid");
    expect(html).not.toContain("data-hermes-token-stream");
  });
});
