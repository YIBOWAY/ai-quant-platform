# Frontend Bilingual (English / 中文) Support

The frontend ships with a site-wide English / Chinese language switch. A single
toggle in the top bar flips the entire UI and the choice is remembered across
visits.

> Updated 2026-06-02. This replaces the earlier cookie-only toggle and
> query-parameter prototype. All main pages are bilingual and can be opened
> through `/en/...` or `/zh/...` paths.

## How To Use

1. Open the app at `http://127.0.0.1:3001`.
2. Click **EN** or **中文** in the top bar.
3. The browser moves to the matching localized path, for example
   `/en/options-radar` or `/zh/options-radar`.
4. The choice is remembered for later unprefixed visits.

The language is site-wide for the current page path. Locale-prefixed URLs are
the preferred way to share a specific language view.

## How It Works

Language can come from a locale path prefix (`/en` or `/zh`), the legacy
`?lang=` query parameter, or a cookie named `qs_lang` (`en` or `zh`, 1-year
lifetime, `path=/`, `samesite=lax`). Server components prefer the path prefix,
then `?lang=`, then the cookie, then English.

| File | Role |
|---|---|
| `src/frontend/lib/locale.ts` | `Locale` type, cookie name, `resolveLocale()`. |
| `src/frontend/lib/serverLocale.ts` | `getServerLocale()` for server components. Priority: locale path header > `?lang` override > cookie > `en`. |
| `src/frontend/components/LocaleProvider.tsx` | Client context + `useLocale()` hook, seeded from the resolved server locale in the root layout. |
| `src/frontend/components/LocaleToggle.tsx` | The top-bar toggle. Sets the cookie and navigates to the matching `/en/...` or `/zh/...` path. |
| `src/frontend/middleware.ts` | Rewrites locale-prefixed paths to the existing app routes and passes the locale through a request header. |

Page text lives in per-component copy dictionaries: a module-level
`const copy = { en: { ... }, zh: { ... } }`, then `const text = copy[locale]`
inside the component. Server pages call `getServerLocale()` and pass
`locale` down to client child components, which keep their own copy dictionary.

Unprefixed paths still work. They use the saved cookie when present and fall
back to English.

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

- The top-bar toggle switches between `/en/...` and `/zh/...`.
- The choice persists after navigating to other pages and after reload.
- Direct visits to `/zh/options-radar` and `/en/options-radar` render the
  expected language.
- Layout stays intact in both languages.
- Buttons still trigger the same backend calls.
- Safety wording is present in both languages.
