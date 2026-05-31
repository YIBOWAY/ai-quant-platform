'use client';

import { useState } from "react";

const THEMES = ["dark", "light", "system"] as const;
type Theme = (typeof THEMES)[number];

const copy = {
  en: {
    title: "Interface",
    description: "Local browser preference only. It does not edit project settings.",
    groupLabel: "Theme",
    themes: { dark: "dark", light: "light", system: "system" } as Record<Theme, string>,
  },
  zh: {
    title: "界面",
    description: "仅为本地浏览器偏好，不会修改项目设置。",
    groupLabel: "主题",
    themes: { dark: "深色", light: "浅色", system: "跟随系统" } as Record<Theme, string>,
  },
} as const;

function applyTheme(theme: Theme) {
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const useDark = theme === "dark" || (theme === "system" && prefersDark);
  document.documentElement.classList.toggle("dark", useDark);
}

export function SettingsThemeSwitcher({ locale = "en" }: { locale?: "en" | "zh" }) {
  const text = copy[locale];
  const [theme, setTheme] = useState<Theme>("dark");

  function selectTheme(nextTheme: Theme) {
    setTheme(nextTheme);
    window.localStorage.setItem("quant-theme", nextTheme);
    applyTheme(nextTheme);
  }

  return (
    <div className="flex flex-col gap-3 rounded border border-border-subtle bg-bg-surface p-4">
      <div>
        <h2 className="font-headline-lg text-text-primary">{text.title}</h2>
        <p className="mt-1 font-body-sm text-text-secondary">
          {text.description}
        </p>
      </div>
      <div className="flex gap-2" role="group" aria-label={text.groupLabel}>
        {THEMES.map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => selectTheme(option)}
            className={`rounded border px-3 py-2 font-label-caps uppercase transition-colors ${
              theme === option
                ? "border-primary bg-primary/10 text-primary"
                : "border-border-subtle text-text-secondary hover:border-text-primary hover:text-text-primary"
            }`}
          >
            {text.themes[option]}
          </button>
        ))}
      </div>
    </div>
  );
}
