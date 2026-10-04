import { createElement, type ComponentProps } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  usePathname: () => "/zh/hermes/sessions/session-1",
  useRouter: () => ({ push: vi.fn() }),
}));

import { HermesWorkbenchShell } from "./HermesWorkbenchShell";

function renderShell(
  props: Omit<Partial<ComponentProps<typeof HermesWorkbenchShell>>, "children"> = {},
) {
  return renderToStaticMarkup(
    createElement(
      HermesWorkbenchShell,
      { locale: "zh", ...props } as ComponentProps<typeof HermesWorkbenchShell>,
      createElement("div", null, "child"),
    ),
  );
}

describe("HermesWorkbenchShell composer admission", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("shows the allowSubmit path when delivery is authorized and chatWriteReady", () => {
    vi.stubEnv("QS_HERMES_CHAT_ENABLED", "true");
    const html = renderShell({
      chatWriteReady: true,
      deliveryState: "local_mutation_authorized",
    });

    expect(html).toContain('data-delivery-state="local_mutation_authorized"');
    expect(html).toContain("Hermes 对话已就绪");
    expect(html).toContain('aria-label="发送"');
    expect(html).not.toContain("发送（已禁用）");
    expect(html).toContain('id="hermes-composer-draft"');
    expect(html).not.toMatch(
      /<div class="sr-only">[\s\S]*id="hermes-composer-draft"/,
    );
  });

  it("shows blocked copy and no enabled send when admission is closed", () => {
    const html = renderShell({
      chatWriteReady: false,
      deliveryState: "local_mutation_authorized",
    });

    expect(html).toContain("Hermes 对话当前不可用");
    expect(html).toContain('data-delivery-state="blocked_in_this_slice"');
    expect(html).not.toContain("Hermes 对话已就绪");
    expect(html).toContain("发送（已禁用）");
    expect(html).not.toContain('aria-label="发送"');
  });
});
