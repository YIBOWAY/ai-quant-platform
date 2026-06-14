# Frontend Optimization Plan with web-design-skill

> 基于 [Garden Skills / web-design-engineer](https://github.com/ConardLi/web-design-skill/tree/main/web-design-engineer) 的系统化界面优化方案。
> 创建时间：2026-06-04
> **状态（2026-06-11）**：本计划已执行完毕——2026-06-07 优化批次 #1/#2 与 2026-06-11 全页面重构均已交付，见 [optimization_log.md](optimization_log.md) 与 [../delivery/frontend_refactor_2026-06-11_delivery.md](../delivery/frontend_refactor_2026-06-11_delivery.md)。本文作为历史规划文档保留。

---

## 1. 为什么选择 web-design-engineer skill

### 当前状态
- ✅ 已有完整设计系统（色板、字体、间距定义在 `globals.css`）
- ✅ 已实现9个页面 + 完整组件库（基于 shadcn/ui）
- ✅ 设计哲学明确（dense professional，参考 Linear/Vercel）

### 需求
- 🎯 **不是**从零生成设计，**是**系统性优化现有界面
- 🎯 提升视觉层次、信息密度、交互流畅度
- 🎯 保持 paper-only 安全红线，不引入 live trading 暗示

### web-design-engineer 的匹配点
1. **25种 anchor styles** 包含 Linear、Vercel Dashboard、Bloomberg Terminal——正是我们的参考目标
2. **六步工作流** 可直接用于单页面/组件优化迭代
3. **Agent-native** 可直接喂给 Claude Code，无需额外工具
4. **Production focus** 强调实战可用，而非概念稿

---

## 2. 六步工作流应用到当前项目

### Phase 1: Requirements（需求明确）
**输入材料：**
- `docs/frontend/design_brief.md` — 完整的设计约束和安全红线
- 当前页面的用户反馈（若有）
- 优化目标（信息密度/可读性/交互流畅度）

**输出：**
- 单页优化的需求文档（3-5条可验证的改进点）

### Phase 2: Context（上下文收集）
**输入材料：**
- 当前页面源码（如 `app/paper-trading/page.tsx`）
- 相关组件（如 `components/forms/AccountTradePanel.tsx`）
- `globals.css` 中的 design tokens
- 当前页面截图

**输出：**
- 设计债务清单（spacing不一致、contrast不足、hierarchy混乱等）

### Phase 3: Design System（锚定风格）
**选定 anchor style：**
- 主锚点：**Linear**（间距、动效、状态反馈）
- 次锚点：**Bloomberg Terminal**（数据密度、表格设计）
- 禁忌：避免 Robinhood/Alpaca 风格的"绿涨红跌大屏"

**输出：**
- 3-5条风格准则（如"卡片间距统一16px"、"状态色必须配合icon"）

### Phase 4: v0（原型草稿）
**使用工具：**
- Figma / Excalidraw（快速布局）
- 或直接在代码中用 Tailwind 快速迭代

**输出：**
- 2-3个设计变体（variant A/B/C）
- 每个变体的 trade-off 说明

### Phase 5: Build（实现）
**执行：**
- 在 feature branch 实现选定变体
- 遵守 design_brief.md 第7节的安全约束
- 运行 `npm run lint` + `npm run type-check`

**输出：**
- 可运行的优化版页面
- Before/After 截图对比

### Phase 6: Verify（验证）
**检查清单：**
- [ ] paper-only 标识始终可见
- [ ] 色彩对比度满足 WCAG AA
- [ ] 所有交互可键盘完成
- [ ] Sample data 图表有 "illustrative only" 角标
- [ ] 移动端响应式正常
- [ ] 中英文文案都补齐

**输出：**
- 验证报告 + 是否merge的决策

---

## 3. 优先优化页面排序

### P0（核心页面，优先优化）
1. **Dashboard** (`app/page.tsx`)  
   **当前问题**：KPI卡片间距不一致、Quick Actions位置不明显  
   **优化方向**：参考 Linear 的 dashboard 密度，统一卡片间距为16px

2. **Backtest** (`app/backtest/page.tsx` + `app/backtest/[runId]/page.tsx`)  
   **当前问题**：equity curve + benchmark 对比不够清晰、metrics 表格信息密度低  
   **优化方向**：参考 Bloomberg Terminal 的图表设计，增加数据密度

3. **Paper Trading** (`app/paper-trading/page.tsx`)  
   **当前问题**：Account panel 与 historical replay 区分不明显、kill switch 位置不够醒目  
   **优化方向**：强化视觉层次，用不同背景色区分"持续账户"和"历史回放"

4. **Position Map** (`app/position-map/page.tsx`)  
   **当前问题**：持仓表格与暴露条形图的关联不直观  
   **优化方向**：增加交互联动（hover 表格行时高亮对应柱子）

### P1（次要页面，后续优化）
5. Factor Lab
6. Data Explorer
7. Experiments
8. Options Screener
9. Settings

---

## 4. 具体操作步骤（以 Dashboard 为例）

### Step 1: 准备上下文材料
```bash
# 当前页面源码
cat src/frontend/app/page.tsx > /tmp/dashboard-context.txt

# 设计系统
cat src/frontend/app/globals.css >> /tmp/dashboard-context.txt
cat docs/frontend/design_brief.md >> /tmp/dashboard-context.txt

# 当前截图（手动截取桌面端和移动端）
# 保存到 docs/frontend/screenshots/dashboard-before-desktop.png
# 保存到 docs/frontend/screenshots/dashboard-before-mobile.png
```

### Step 2: 创建优化 prompt（喂给 Claude Code）
```markdown
I'm using the web-design-engineer skill from Garden Skills to optimize the Dashboard page.

**Context:**
- Current implementation: [paste app/page.tsx content]
- Design system: [paste globals.css @theme section]
- Design brief: [paste design_brief.md §2-4]

**Current problems:**
1. KPI cards have inconsistent spacing (some 12px, some 16px)
2. Quick Actions sidebar is visually weak (same color as card backgrounds)
3. Run cards lack hover feedback
4. Mobile layout breaks at 768px

**Optimization goals:**
1. Unify card spacing to 16px (Linear style)
2. Elevate Quick Actions with border + bg-surface-2
3. Add subtle hover states to run cards (border-accent)
4. Fix mobile breakpoint to 640px (Tailwind sm)

**Anchor styles:** Linear (spacing), Vercel Dashboard (card density)

**Safety constraints (non-negotiable):**
- paper-only strip must remain visible
- No "connect wallet" / "submit order" buttons
- Sample data must have "illustrative only" tag

Please generate 2 design variants (A: minimal changes, B: bolder redesign) following the six-step workflow. Output the final TSX code for variant A.
```

### Step 3: 实现 + 验证
```bash
# 创建 feature branch
git checkout -b optimize/dashboard-density

# 实现优化（AI生成的代码）
# 修改 src/frontend/app/page.tsx

# 本地验证
npm run dev
# 手动检查桌面端 + 移动端

# 截图 after
# 保存到 docs/frontend/screenshots/dashboard-after-desktop.png

# 类型检查
npm run type-check

# Lint
npm run lint

# Commit
git add .
git commit -m "feat(dashboard): optimize card spacing and Quick Actions visibility

- Unify card gap to 16px (Linear style)
- Elevate Quick Actions with border + bg-surface-2
- Add hover:border-accent to run cards
- Fix mobile breakpoint to sm (640px)

Ref: web-design-engineer skill, variant A"

# PR
git push origin optimize/dashboard-density
```

### Step 4: Before/After 对比验证
创建 `docs/frontend/optimization_log.md` 记录每次优化：
```markdown
## Dashboard Optimization — 2026-06-04

### Before
![](screenshots/dashboard-before-desktop.png)

### After
![](screenshots/dashboard-after-desktop.png)

### Changes
- Card spacing: 12px/16px混杂 → 统一16px
- Quick Actions: 弱对比 → border + bg-surface-2
- Run cards: 无hover → hover:border-accent
- Mobile: 768px break → 640px (Tailwind sm)

### Metrics
- WCAG contrast: AA ✅
- Keyboard nav: ✅
- Mobile responsive: ✅
- Safety strip visible: ✅

### Trade-offs
- 信息密度略降（16px gap vs 12px），但一致性提升
- Quick Actions 更醒目，但占用更多视觉权重

### Verdict: ✅ Merged
```

---

## 5. 与 Open Design 的对比

| 维度 | web-design-skill（选用） | Open Design（未选用） |
|---|---|---|
| **适用阶段** | 优化现有界面 | 从零生成设计系统 |
| **工具复杂度** | 轻量（SKILL.md） | 重量（桌面应用 + MCP） |
| **学习曲线** | 低（直接喂给AI） | 中（需学习skill/system/plugin三层） |
| **风格库** | 25种精选 | 150+ 通用系统 |
| **输出格式** | TSX/JSX代码 | HTML/PDF/MP4 |
| **当前项目匹配** | ✅ 完美匹配 | ❌ 过重 |

**Open Design 更适合的场景：**
- 需要快速生成pitch deck、landing page、marketing materials
- 团队需要统一的design artifact生成平台
- 从零开始的新项目，需要建立设计系统

---

## 6. 下一步行动

### 立即执行（本周）
1. [ ] 下载 [web-design-engineer skill](https://github.com/ConardLi/web-design-skill/tree/main/web-design-engineer) 到本地
2. [ ] 优化 Dashboard（P0-1）
3. [ ] 优化 Backtest detail page（P0-2）

### 短期（2周内）
4. [ ] 优化 Paper Trading（P0-3）
5. [ ] 优化 Position Map（P0-4）
6. [ ] 创建 `optimization_log.md` 记录每次改动

### 中期（1个月）
7. [ ] 优化 P1 页面（Factor Lab / Data Explorer / Experiments）
8. [ ] 提取共性优化为 design tokens（如新增 `--spacing-card-gap: 16px`）
9. [ ] 更新 design_brief.md 的 §5 组件清单

---

## 7. 风险与限制

### 不要做的事（安全红线）
- ❌ 隐藏或弱化 paper-only strip
- ❌ 引入任何 live trading 暗示（"connect wallet"/"submit order"按钮）
- ❌ 把 sample data 的 Sharpe/IC 当作真实策略效果展示
- ❌ 编辑因子源码 / risk limits / .env 内容的UI

### 技术债务
- 当前 `globals.css` 的 design tokens 散乱（部分在 `@theme`，部分在 `@layer utilities`）
- 需要在优化过程中逐步整理，但不强求一次性重构

### 团队协作
- 优化过程中，所有改动必须保持 `copy = { en, zh }` 文案双语
- 每次 PR 必须包含 before/after 截图
- 大改动（如整页重构）需要在 `optimization_log.md` 记录 trade-offs

---

## 8. 参考资料

- [web-design-engineer skill](https://github.com/ConardLi/web-design-skill/tree/main/web-design-engineer)
- [Linear Design System](https://linear.app) — spacing & motion
- [Vercel Dashboard](https://vercel.com) — card density
- [Bloomberg Terminal UI](https://www.bloomberg.com/professional/solution/bloomberg-terminal/) — data density
- 当前项目 [design_brief.md](design_brief.md)
- 当前项目 [globals.css](../../src/frontend/app/globals.css)

---

**Created:** 2026-06-04  
**Last updated:** 2026-06-04  
**Owner:** Frontend optimization team  
**Status:** Draft → Ready for execution
