import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { SecuritySearchInput } from "./SecuritySearchInput";

describe("SecuritySearchInput", () => {
  it("keeps direct ticker input and does not claim directory results before a request", () => {
    const html = renderToStaticMarkup(<SecuritySearchInput label="标的代码" value="DELL" onChange={() => undefined} />);
    expect(html).toContain('role="combobox"');
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain('value="DELL"');
    expect(html).not.toContain('role="listbox"');
  });
});
