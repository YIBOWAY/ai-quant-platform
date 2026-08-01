import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { TodayStateNode } from "@/components/hermes/today/TodayStateNode";
import { HermesChatActiveProvider } from "@/lib/hermes/chatActiveContext";

describe("TodayStateNode", () => {
  it("owns the hermes-today-state test id when chat is not active", () => {
    const html = renderToStaticMarkup(
      <TodayStateNode label="read-only desk" state="normal" />,
    );
    expect(html).toContain('data-testid="hermes-today-state"');
    expect(html).toContain('data-state="normal"');
    expect(html).toContain("read-only desk");
  });

  it("releases the test id while fullscreen chat is active", () => {
    // Today stays mounted (hidden) under fullscreen chat; two nodes carrying the
    // same test id would break Playwright's strict getByTestId.
    const html = renderToStaticMarkup(
      <HermesChatActiveProvider active>
        <TodayStateNode label="read-only desk" state="normal" />
      </HermesChatActiveProvider>,
    );
    expect(html).toBe("");
  });
});
