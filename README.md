# AI-Assisted Quant Research and Paper-Trading Platform

本项目正在从 Phase 0 开始搭建一个可回测、可迭代因子、可逐步接入模拟交易，并为未来实盘接口保留边界的量化研究工程系统。

当前阶段只完成工程基础，不包含真实数据下载、回测引擎、券商接口、AI Agent 下单或 Polymarket 交易。

## 当前状态

Phase 0 已包含：

- Python 项目骨架
- conda + pip 环境文件
- 安全默认配置
- 结构化日志
- 基础 CLI
- 风控默认值
- 因子、策略、组合优化器的插件接口占位
- pytest 测试
- Phase 0 学习、执行和架构文档

## 安全边界

默认配置是保守的：

- `dry_run = true`
- `paper_trading = true`
- `live_trading_enabled = false`
- `no_live_trade_without_manual_approval = true`
- `kill_switch = true`

当前系统不会真实下单，也不会连接券商。

## 安装

推荐使用 conda：

```powershell
conda env create -f environment.yml
conda activate ai-quant
```

如果已经有 Python 3.11 环境，也可以直接安装：

```powershell
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"
```

## 运行

```powershell
quant-system --help
quant-system config show
quant-system doctor
```

也可以用模块方式运行：

```powershell
python -m quant_system.cli --help
```

## 验证

```powershell
python -m pytest
ruff check .
```

成功标志：

- pytest 全部通过
- ruff 没有报错
- `quant-system config show` 显示真实交易默认关闭

## 文档

- `docs/SYSTEM_DESIGN_RESEARCH.md`：系统设计研究
- `docs/phase_0_learning.md`：Phase 0 学习文档
- `docs/phase_0_execution.md`：Phase 0 执行文档
- `docs/phase_0_architecture.md`：Phase 0 架构文档
- `docs/phase_0_delivery.md`：Phase 0 交付清单

## 下一步

Phase 0 完成后暂停。用户确认后再进入 Phase 1：数据层 MVP。
