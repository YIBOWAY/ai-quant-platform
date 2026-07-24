import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const globalsCss = readFileSync(path.join(process.cwd(), "app/globals.css"), "utf8");

function classBlock(className: string): string {
  const escapedClassName = className.replace(".", "\\.");
  const match = globalsCss.match(new RegExp(`${escapedClassName}\\s*\\{([\\s\\S]*?)\\n\\}`));

  return match?.[1] ?? "";
}

describe("editorial typography utilities", () => {
  it("enables the Tailwind typography plugin", () => {
    expect(globalsCss).toContain('@plugin "@tailwindcss/typography";');
  });

  it("defines editorial display, body, and caption typography on the editorial serif stack", () => {
    expect(classBlock(".font-editorial-display")).toContain("font-family: var(--font-editorial-serif);");
    expect(classBlock(".font-editorial-body")).toContain("font-family: var(--font-editorial-serif);");
    expect(classBlock(".font-editorial-caps")).toContain("font-family: var(--font-editorial-serif);");
  });

  it("keeps editorial display tracking neutral instead of negative", () => {
    const displayBlock = classBlock(".font-editorial-display");

    expect(displayBlock).toContain("letter-spacing: 0;");
    expect(displayBlock).not.toMatch(/letter-spacing:\s*-/);
  });
});
