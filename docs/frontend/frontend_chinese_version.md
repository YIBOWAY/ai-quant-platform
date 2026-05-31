# Frontend Bilingual (English / 中文) Support

The frontend ships with a site-wide English / Chinese language switch. A single
toggle in the top bar flips the entire UI and the choice is remembered across
visits.

> Updated 2026-05-29. This replaces the earlier query-parameter prototype that
> only covered `/data-explorer` and `/options-screener`. All main pages are now
> bilingual through one global toggle.

## How To Use

1. Open the app at `http://127.0.0.1:3001`.
2. Click the language button in the top bar (shows **中文** while in English,
   **EN** while in Chinese).
3. The whole site switches immediately and stays in that language on later
   visits.

There is no separate Chinese URL. The language is global, not per-page.

## How It Works

Language is stored in a cookie named `qs_lang` (`en` or `zh`, 1-year lifetime,
`path=/`, `samesite=lax`). Both server and client components read the same
cookie so the first server render already matches the chosen language.

| File | Role |
|---|---|
| `src/frontend/lib/locale.ts` | `Locale` type, cookie name, `resolveLocale()`. |
| `src/frontend/lib/serverLocale.ts` | `getServerLocale()` for server components. Priority: `?lang` override > cookie > `en`. |
| `src/frontend/components/LocaleProvider.tsx` | Client context + `useLocale()` hook, seeded from the cookie in the root layout. |
| `src/frontend/components/LocaleToggle.tsx` | The top-bar toggle. Sets the cookie, strips any `?lang` query, then refreshes. |

Page text lives in per-component copy dictionaries: a module-level
`const copy = { en: { ... }, zh: { ... } }`, then `const text = copy[locale]`
inside the component. Server pages call `getServerLocale()` and pass
`locale` down to client child components, which keep their own copy dictionary.

Note: the root layout, shared chrome (sidebar, top bar, safety strip), and the
dashboard read the cookie only, so the `?lang=` query string switches only the
body of pages that explicitly read it — the global toggle is the supported way
to change language everywhere.

## Coverage

Shared chrome (sidebar, top bar, safety strip) plus all main pages and their
forms are translated, including: dashboard, data explorer, options screener,
options radar, options tools, buy-side options, factor lab, backtester,
replications, experiments, paper trading, agent studio, order book,
position map, and settings.

A small number of low-level form validation messages and data-provider enum
values (for example `futu` / `sample` / `tiingo`) remain in English by design.

## Beginner-Friendly Tooltips

Jargon terms (APR, IV, IV rank, delta, theta burn, IV crush, break-even,
net debit, spread, open interest, market regime, and more) carry inline
glossary tooltips via `src/frontend/components/InfoTip.tsx`. The glossary is
bilingual and follows the active language.

## Safety Copy

The read-only safety message is translated, not removed. Both languages keep the
same meaning, for example:

```text
EN: Paper only · Live trading disabled · Kill switch on
ZH: 仅模拟 · 实盘交易已禁用 · 熔断开关 开
```

## Manual Verification

```text
http://127.0.0.1:3001
```

Check:

- The top-bar toggle switches the whole site between English and Chinese.
- The choice persists after navigating to other pages and after reload.
- Layout stays intact in both languages.
- Buttons still trigger the same backend calls.
- Safety wording is present in both languages.
