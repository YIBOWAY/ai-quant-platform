# 阶段 13 Windows 调度器配置

使用 Windows 任务计划程序 (Windows Task Scheduler)。不要写入注册表项或开机自启动条目。

## 触发器

- 频率：每个工作日
- 时间：北京时间 (BJT) 06:30
- 理由：在美股收盘之后

## 注册任务

推荐使用仓库脚本注册 Windows 计划任务：

```powershell
.\scripts\register_options_radar_task.ps1
```

默认任务名为 `AIQuant Options Radar Daily Task`，触发时间为北京时间 06:30，
每周一到周五运行一次。可按需覆盖：

```powershell
.\scripts\register_options_radar_task.ps1 -TaskName "AIQuant Options Radar Daily Task" -StartTime "06:30"
```

该注册脚本只调用 `schtasks.exe /Create`，不会立即启动扫描；扫描仍由
`scripts/run_options_radar.ps1` 在计划任务触发时执行。

## 手工配置等价操作

程序：

```text
powershell.exe
```

参数：

```text
-ExecutionPolicy Bypass -File E:\programs\AI-assisted_quant_research_and_paper-trading_platform\scripts\run_options_radar.ps1
```

## 条件

- 仅在网络可用时运行。
- 在任务触发前，保持 OpenD 处于运行并已登录状态。

## 脚本

```powershell
scripts/run_options_radar.ps1
```

该脚本会按顺序寻找可用解释器：

- `conda info --base` 下的 `envs\ai-quant\python.exe`
- 当前 `CONDA_PREFIX` 下的 `python.exe`
- `PATH` 中的 `python`

然后调用：

```text
python -m quant_system.cli options daily-task --top 100 --universe-source public --earnings-source public --vix-source public
```

该命令会先刷新本地标的池、财报日历和 VIX/VIX3M 历史，再运行只读
期权雷达扫描。`daily-scan` 仍可用于人工调试或只扫描已有输入缓存。
调度任务、CLI 手动扫描、API 手动扫描和 API 启动补跑会共享雷达输出目录下的
`options_radar_scan.lock`，避免多个进程同时写每日快照、IV history 或任务状态。

调度输出会追加到：

```text
data/_runtime/logs/options-radar.log
```

最近一次任务状态会写入雷达输出目录：

```text
data/options_scans/daily_task_status.json
```

本地 API 会通过 `GET /api/options/daily-scan/status` 只读暴露同一文件；
`/options-radar` 页面顶部的「定时任务」状态块会显示最近一次完成/失败状态、
扫描日期、候选数、失败步骤和完成时间。

可选启动补跑：

```powershell
$env:QS_OPTIONS_RADAR_STARTUP_CATCHUP_ENABLED='true'
```

该开关默认关闭。开启后，API 启动时如果最近一个 UTC 工作日雷达快照缺失，会在后台运行一次
只读 `daily-scan` 等价扫描；周末启动会回退到上一个周五，并把
`source=startup_catchup` 的状态写入同一个 `daily_task_status.json`。它只使用已有本地输入缓存；
正式日终刷新和完整交易所节假日处理仍应使用 Windows 任务计划程序调用 `daily-task`。
如果扫描锁已被调度任务或手动扫描持有，启动补跑会跳过且不覆盖已有
`daily_task_status.json`；CLI/API 手动扫描遇锁会快速失败，稍后重试即可。
