# 每日晨报双入口 — Design + Implementation Plan

> **For agentic workers:** Implement task-by-task. Steps use checkbox syntax.

**Goal:** Give the existing `/brief` (每日晨报 / Daily Morning Brief) page discoverable dual entry points: global sidebar + Hermes Today contextual CTA.

**Architecture:** Reuse `navConfig` for the global/mobile surface; add a pure navigation pill on `HermesTodayView` header. No new APIs, no Hermes internal-tab pollution, no TopBar icon clutter.

**Tech Stack:** Next.js 15 App Router, React 19, TypeScript, Tailwind 4, lucide-react, Vitest.

**Repo:** `/Users/sunyibo/programs/ai-quant-platform` (frontend at `src/frontend`). Not HQA.

## Global Constraints

- Product name: zh `每日晨报`, en `Morning Brief` (align with brief page title family; not "每日日报").
- Route: `/brief` via `localizePath`; archive `/brief/[publicId]` must keep sidebar active.
- Design system: hairline borders, `rounded-lg`, info blue for nav/actions, success green reserved for financial outcomes, no shadows, no gradients, no emoji.
- No new network calls on the entry itself.
- Do not add brief to `HermesInternalNav` tabs (not a `/hermes/*` surface).
- Do not add TopBar icon (scheme A).

## Design

### IA

| Entry | Location | Role |
|---|---|---|
| Global | Sidebar Research Pipeline, directly under Hermes | Always-on discovery |
| Contextual | Hermes Today header, right side pill | First action on home desk |
| Mobile | Existing TopBar mobile menu via same `navConfig` | Small-screen reach |

### Visual

**Sidebar item:** identical to other Research items. Icon `Newspaper` size 18. Active when `activePath === "/brief" || activePath.startsWith("/brief/")`.

**Today CTA:**
- Layout: header becomes `flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between`
- Left: existing TODAY label + state h1 + description
- Right: Link pill
  - classes: `app-touch-target inline-flex shrink-0 items-center gap-2 rounded-lg border border-info/40 bg-info/5 px-3 font-body-sm text-info transition-colors hover:bg-info/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info`
  - content: `<Newspaper size={16} />` + label + `›`
  - `data-testid="hermes-today-brief-entry"`
  - `aria-label`: zh `打开每日晨报` / en `Open morning brief`
  - href: `localizePath("/brief", locale)`

### Copy

| Surface | zh | en |
|---|---|---|
| Sidebar / mobile nav | 每日晨报 | Morning Brief |
| Today CTA label | 每日晨报 | Morning Brief |
| Today CTA aria | 打开每日晨报 | Open morning brief |

### Files

| File | Change |
|---|---|
| `src/frontend/lib/navConfig.ts` | Add `brief` NavItemId + item after hermes |
| `src/frontend/lib/navConfig.test.ts` | Expect brief in research routes + id lists |
| `src/frontend/components/Sidebar.tsx` | nav copy + prefix active for `/brief` |
| `src/frontend/components/TopBar.tsx` | nav copy + prefix active for `/brief` |
| `src/frontend/lib/hermes/copy.ts` | `labels.openMorningBrief` + `labels.openMorningBriefAria` |
| `src/frontend/components/hermes/today/HermesTodayView.tsx` | header CTA |
| `src/frontend/lib/hermesArtifactShelf.test.ts` | assert CTA href + label in zh render |

## Out of scope

- Redesigning `/brief` page
- Pulling live brief summary into the CTA
- TopBar icon, Hermes internal tab, triple-entry masthead card
- Backend / HQA changes

---

## Task 1: Nav config + tests (TDD)

**Files:**
- Modify: `src/frontend/lib/navConfig.ts`
- Modify: `src/frontend/lib/navConfig.test.ts`

- [ ] **Step 1: Update failing expectations in navConfig.test.ts**

Insert `"brief"` immediately after `"hermes"` in both `expectedEnabledItemIds` and `expectedRolledBackItemIds`.

In `keeps exact item routes…`, insert `{ id: "brief", href: "/brief" }` immediately after the hermes row in both enabled and rolledBack research arrays.

- [ ] **Step 2: Run test — expect FAIL**

```bash
cd /Users/sunyibo/programs/ai-quant-platform/src/frontend && npm test -- --run lib/navConfig.test.ts
```

Expected: FAIL — research routes missing brief.

- [ ] **Step 3: Implement navConfig.ts**

1. Import `Newspaper` from `lucide-react`.
2. Extend `NavItemId` with `| "brief"`.
3. Add:

```ts
const briefItem: NavItem = {
  id: "brief",
  href: "/brief",
  icon: Newspaper,
};
```

4. In `buildNavSections`, research items become:

```ts
const researchItems: NavItem[] = shellEnabled
  ? [hermesItem, briefItem, ...researchTail]
  : [dashboardItem, hermesItem, briefItem, ...researchTail];
```

- [ ] **Step 4: Run test — expect PASS**

```bash
cd /Users/sunyibo/programs/ai-quant-platform/src/frontend && npm test -- --run lib/navConfig.test.ts
```

---

## Task 2: Sidebar + TopBar labels and brief active matching

**Files:**
- Modify: `src/frontend/components/Sidebar.tsx`
- Modify: `src/frontend/components/TopBar.tsx`

- [ ] **Step 1: Sidebar copy**

In `copy.en.nav` add `brief: "Morning Brief"`.
In `copy.zh.nav` add `brief: "每日晨报"`.

- [ ] **Step 2: Sidebar active helper**

Replace exact-only active check with:

```ts
const isActive =
  activePath === item.href ||
  (item.href !== "/" && activePath.startsWith(`${item.href}/`));
```

(Keeps dashboard `/` from matching everything; lights `/brief/[publicId]`.)

- [ ] **Step 3: TopBar copy + active**

Add `brief: "Morning Brief"` / `brief: "每日晨报"` to TopBar `copy.en` / `copy.zh` (same level as other nav labels — TopBar uses flat copy, not `nav.` nested).

In mobile menu link classes, replace `activePath === item.href` with the same prefix-aware check as Sidebar (both `aria-current` and className).

---

## Task 3: Hermes Today CTA

**Files:**
- Modify: `src/frontend/lib/hermes/copy.ts`
- Modify: `src/frontend/components/hermes/today/HermesTodayView.tsx`
- Modify: `src/frontend/lib/hermesArtifactShelf.test.ts`

- [ ] **Step 1: Extend HermesWorkbenchCopy.labels**

```ts
openMorningBrief: string;
openMorningBriefAria: string;
```

en: `"Morning Brief"`, `"Open morning brief"`
zh: `"每日晨报"`, `"打开每日晨报"`

- [ ] **Step 2: HermesTodayView header**

```tsx
import Link from "next/link";
import { Newspaper } from "lucide-react";
import { localizePath } from "@/lib/locale";

// header:
<header className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
  <div className="min-w-0 space-y-2">
    <p className="font-label-caps uppercase text-text-secondary">
      {locale === "zh" ? "今日" : "Today"}
    </p>
    <h1 className="font-headline-lg text-text-primary" id="hermes-today-title">
      {copy.states[model.state]}
    </h1>
    <p className="font-body-sm text-text-secondary">
      {locale === "zh"
        ? "以行动、异常与结论为先的只读研究工作台。提交仍保持禁用。"
        : "Read-only research desk prioritizing action, exceptions, and conclusions. Submit remains disabled."}
    </p>
  </div>
  <Link
    aria-label={copy.labels.openMorningBriefAria}
    className="app-touch-target inline-flex shrink-0 items-center gap-2 self-start rounded-lg border border-info/40 bg-info/5 px-3 font-body-sm text-info transition-colors hover:bg-info/10 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-info"
    data-testid="hermes-today-brief-entry"
    href={localizePath("/brief", locale)}
  >
    <Newspaper aria-hidden size={16} />
    <span>{copy.labels.openMorningBrief}</span>
    <span aria-hidden className="text-info/80">›</span>
  </Link>
</header>
```

- [ ] **Step 3: Assert in hermesArtifactShelf.test.ts**

In the first HermesTodayView zh render test (automation/approvals one), add:

```ts
expect(html).toContain('data-testid="hermes-today-brief-entry"');
expect(html).toContain('href="/zh/brief"');
expect(html).toContain("每日晨报");
expect(html).toContain('aria-label="打开每日晨报"');
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/sunyibo/programs/ai-quant-platform/src/frontend && npm test -- --run lib/navConfig.test.ts lib/hermesArtifactShelf.test.ts
```

Expected: PASS.

---

## Task 4: Live browser verification

- [ ] Open `http://127.0.0.1:3001/zh/hermes` (or hard refresh)
- [ ] Sidebar shows 每日晨报 under Hermes 工作台; click → `/zh/brief`
- [ ] Today header shows pill; click → `/zh/brief`
- [ ] On `/zh/brief`, sidebar item is active
- [ ] Mobile menu (narrow) includes 每日晨报

## Self-review

- Spec coverage: dual entry, naming, active prefix, no internal-tab, no TopBar icon, no API — all tasked.
- No placeholders.
- Types: `NavItemId` + copy labels aligned across tasks.
