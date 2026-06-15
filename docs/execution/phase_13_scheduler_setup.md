# 阶段 13 Windows 调度器配置

使用 Windows 任务计划程序 (Windows Task Scheduler)。不要写入注册表项或开机自启动条目。

## 触发器

- 频率：每个工作日
- 时间：北京时间 (BJT) 06:30
- 理由：在美股收盘之后

## 操作

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

调度输出会追加到：

```text
data/_runtime/logs/options-radar.log
```

最近一次任务状态会写入雷达输出目录：

```text
data/options_scans/daily_task_status.json
```
