# 阶段 13 调度配置

## macOS / Hermes 现役合同

本机正式推荐供血由 HQA 拥有，不由 Platform FastAPI 或本页的 Windows 脚本拥有：

- 现役 owner：Hermes cron job `hqa-options-collect`；
- schedule：`0 22 * * 1-6`，即北京时间周一至周六 22:00；
- wrapper：`~/.hermes/scripts/hqa-options-collect.sh`；
- 周一至周五：真实 Futu + tracked exact 34 策展标的；
- 周六：先跑同一正式 34 标的，再顺序运行独立 top-100 宽池；
- 宽池写 `data/options_scans/wide`，不进入正式推荐页；
- 财报、除息事件和 VIX 在扫描前刷新；正式策展名单只加载，不由页面或任务联网替换；
- sample 输入、输出和 IV history 不得进入正式目录；
- API startup catch-up 已退役，机器错过 22:00 时如实保留缺席。

仓库还保留 dormant `com.aiquant.options-collect` LaunchAgent 资产，作为替代调度机制，
**不得与现役 Hermes cron 同时加载**。完整安装、检查、日志与 owner 操作只看
[HQA 期权推荐运维 runbook](https://github.com/YIBOWAY/Hermes-quant-agent/blob/main/docs/runbooks/options-recommendations.md)。

截至 2026-08-26，22:00 新 schedule 的首次自然触发尚未发生；配置和下一次运行时间
不能代替自然触发证据。

## Platform 任务入口

正式 wrapper 调用的 Platform 合同等价于：

```bash
./ai-quant/bin/quant-system options daily-task \
  --provider futu \
  --top 34 \
  --universe-source existing \
  --universe-path data/options_universe/curated_wheel.csv \
  --output-dir data/options_scans
```

未显式传入的财报、除息和 VIX source 使用当前公开默认值。任务、页面手动更新和其他
CLI 写入共用 `options_radar_scan.lock`。遇锁时不会启动第二份扫描。

状态写入：

```text
data/options_scans/daily_task_status.json
```

API 与页面只读同一状态：

```text
GET /api/options/daily-scan/status
```

## Windows Task Scheduler 边界

`scripts/register_options_radar_task.ps1` 和 `scripts/run_options_radar.ps1` 是旧的 Windows
等价入口，不是本机现役调度。注册脚本仍按北京时间 06:30、周一至周五创建任务，且
runner 仍调用历史的 `--top 100 --universe-source public` 组合；当前正式输出合同会拒绝
这组参数。因此，**在脚本更新并验证前不要注册或宣称 Windows 自动任务可用**。

若需要在 Windows 前台人工运行当前正式合同，使用上一节的 exact-34 `daily-task`
命令，并确保 OpenD 已启动登录。不要用 Windows runner 的旧 top-100 命令写正式目录。

这个 Windows 脚本差异是尚未处理的跨平台边界；本次文档同步没有修改脚本代码。
