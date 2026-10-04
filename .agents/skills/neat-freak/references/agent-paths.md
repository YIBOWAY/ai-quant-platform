# Agent 配置与记忆路径速查

执行 `neat-freak` 盘点时，先识别当前宿主实际提供的配置与记忆机制；不要假定所有宿主都相同，也不要把“发现记忆”理解为“获准修改记忆”。

## Claude Code

| 用途 | 常见路径 |
|---|---|
| 跨会话记忆 | `~/.claude/projects/<encoded-project-path>/memory/` |
| 全局兼容入口 | `~/.claude/CLAUDE.md`，跟随其 canonical AGENTS.md 引用 |
| 项目兼容入口 | 项目根 `CLAUDE.md`，指向该项目 AGENTS.md；不重复规则正文 |
| Skills | `~/.claude/skills/<name>/SKILL.md` |

## OpenAI Codex

| 用途 | 常见路径 |
|---|---|
| 全局指令 | `~/.codex/AGENTS.md` 或宿主给出的 `$CODEX_HOME/AGENTS.md` |
| 项目指令 | 项目根 `AGENTS.md`，可按目录嵌套 |
| 项目 override | `AGENTS.override.md`（若存在） |
| Skills | `~/.codex/skills/<name>/SKILL.md` 或项目内 skill 目录 |
| 记忆 | 仅在当前宿主明确暴露时按宿主说明读取；写入仍以宿主授权规则为准 |

## OpenCode

| 用途 | 常见路径 |
|---|---|
| 全局配置 | `~/.config/opencode/` |
| 项目配置 | `.opencode/` |
| Skills | `.opencode/skills/`、`.claude/skills/`、`.codex/skills/` |

## OpenClaw

| 用途 | 常见路径 |
|---|---|
| 用户 Skills | `~/.openclaw/skills/<name>/SKILL.md` |
| 项目 Skills | `.openclaw/skills/<name>/SKILL.md` |
| Workspace Skills | 当前 workspace 的 `skills/` |

## 通用判断

- 宿主没有独立记忆机制时，跳过记忆层，集中同步项目根说明、`README` 和 `docs/`。
- 只读取当前宿主实际生效、或本次明确要求核对的配置；不要因为目录存在就遍历其他宿主、缓存、会话或凭据。
- 全局规则以当前生效的 canonical AGENTS.md 为准；CLAUDE.md 是兼容入口时跟随引用，不另存一套规则。
- 项目文档保持平台中立；不要为每种 agent 复制一套产品说明。
