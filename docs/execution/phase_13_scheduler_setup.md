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

该脚本使用：

```text
D:\anaconda3\envs\ai-quant\python.exe
```

并调用：

```text
python -m quant_system.cli options daily-scan --top 100
```
