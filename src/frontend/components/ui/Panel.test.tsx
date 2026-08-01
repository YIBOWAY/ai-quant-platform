import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Panel } from "@/components/ui/Panel";

describe("Panel", () => {
  it("renders the title in the header", () => {
    const html = renderToStaticMarkup(
      <Panel title="Approvals">
        <p>body</p>
      </Panel>,
    );
    expect(html).toContain("Approvals");
    expect(html).toContain("font-label-caps");
  });

  it("renders the count badge only when count is a number", () => {
    const withCount = renderToStaticMarkup(
      <Panel count={3} title="Approvals">
        <p>body</p>
      </Panel>,
    );
    expect(withCount).toContain("rounded-full");
    expect(withCount).toContain(">3<");

    const withoutCount = renderToStaticMarkup(
      <Panel count={null} title="Approvals">
        <p>body</p>
      </Panel>,
    );
    expect(withoutCount).not.toContain("rounded-full");
  });

  it("renders the error line with role=alert", () => {
    const html = renderToStaticMarkup(
      <Panel error="gateway unreachable" title="Approvals">
        <p>body</p>
      </Panel>,
    );
    expect(html).toContain('role="alert"');
    expect(html).toContain("gateway unreachable");
    expect(html).toContain("text-danger");
  });

  it("swaps children for the empty placeholder when isEmpty is set", () => {
    const html = renderToStaticMarkup(
      <Panel empty="no pending approvals" isEmpty title="Approvals">
        <p>CHILD_MARKER</p>
      </Panel>,
    );
    expect(html).toContain("no pending approvals");
    expect(html).not.toContain("CHILD_MARKER");
  });

  it("names the section landmark via its own heading", () => {
    const html = renderToStaticMarkup(
      <Panel title="Approvals">
        <p>body</p>
      </Panel>,
    );
    const labelledBy = /aria-labelledby="([^"]+)"/.exec(html)?.[1];
    expect(labelledBy).toBeTruthy();
    expect(html).toContain(`id="${labelledBy}"`);
    // The referenced element is the heading that carries the title text.
    expect(html).toMatch(
      new RegExp(`<h3[^>]*id="${labelledBy}"[^>]*>Approvals</h3>`),
    );
  });

  it("gives each panel instance a distinct heading id", () => {
    const html = renderToStaticMarkup(
      <>
        <Panel title="Approvals">
          <p>a</p>
        </Panel>
        <Panel title="Activity">
          <p>b</p>
        </Panel>
      </>,
    );
    const ids = [...html.matchAll(/aria-labelledby="([^"]+)"/g)].map((m) => m[1]);
    expect(ids).toHaveLength(2);
    expect(new Set(ids).size).toBe(2);
  });

  it("renders children, headerExtra, and forwards data-* attributes", () => {
    const html = renderToStaticMarkup(
      <Panel
        data-hermes-approvals-panel="true"
        headerExtra={<a href="/receipt">receipt</a>}
        title="Approvals"
      >
        <p>body</p>
      </Panel>,
    );
    expect(html).toContain("<p>body</p>");
    expect(html).toContain('href="/receipt"');
    expect(html).toContain('data-hermes-approvals-panel="true"');
    expect(html).toContain("rounded-[var(--radius-card)]");
  });
});
