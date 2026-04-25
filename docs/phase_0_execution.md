# Phase 0 执行文档

## 环境要求

- Windows PowerShell
- conda
- Python 3.11+
- 网络可用时可自动安装依赖

本阶段默认使用 conda + pip：

- conda 创建 Python 运行环境
- pip 以 editable 方式安装当前项目

## 安装步骤

推荐方式：

```powershell
conda env create -f environment.yml
conda activate ai-quant
```

如果已经存在 Python 3.11 环境：

```powershell
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"
```

## 配置步骤

默认不需要创建 `.env`。系统会使用内置安全默认值。

如需本地覆盖配置：

```powershell
Copy-Item .env.example .env
```

保持以下值不变，除非未来通过 live readiness checklist：

```text
QS_DRY_RUN=true
QS_PAPER_TRADING=true
QS_LIVE_TRADING_ENABLED=false
QS_NO_LIVE_TRADE_WITHOUT_MANUAL_APPROVAL=true
QS_KILL_SWITCH=true
```

## 启动步骤

查看命令：

```powershell
quant-system --help
```

查看配置：

```powershell
quant-system config show
```

运行健康检查：

```powershell
quant-system doctor
```

模块方式也可运行：

```powershell
python -m quant_system.cli --help
```

## 测试步骤

运行测试：

```powershell
python -m pytest
```

运行代码检查：

```powershell
ruff check .
```

## 成功运行标志

成功时应看到：

- `python -m pytest` 显示所有测试通过
- `ruff check .` 显示无错误
- `quant-system config show` 中 `live_trading_enabled` 为 `false`
- `quant-system doctor` 输出 `Phase 0 foundation is available`

## 常见报错排查

### 1. Python 版本过低

现象：

```text
requires-python >=3.11
```

处理：

```powershell
conda env create -f environment.yml
conda activate ai-quant
```

### 2. 找不到 quant-system 命令

原因通常是没有激活环境，或没有安装 editable 包。

处理：

```powershell
conda activate ai-quant
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"
```

### 3. 找不到 quant_system 包

说明项目还没有安装到当前 Python 环境。

处理：

```powershell
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"
```

### 4. live trading 配置报错

如果把 `QS_LIVE_TRADING_ENABLED=true` 打开，但没有设置确认短语，系统会拒绝加载配置。

这是预期行为。Phase 0 不允许默认实盘。

### 5. pandas / numpy / pyarrow 版本冲突

现象可能是导入 pandas 或 pyarrow 时出现二进制兼容错误。

处理：

```powershell
conda activate ai-quant
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"
```

本项目在 `pyproject.toml` 中约束了 `numpy<2`，减少这类冲突。

### 6. Windows 下 `conda run` 输出编码报错

如果使用 `conda run -n ai-quant quant-system --help` 时出现编码报错，优先使用正常激活环境的方式：

```powershell
conda activate ai-quant
quant-system --help
```

如果必须使用 `conda run`，先设置 UTF-8 输出：

```powershell
$env:PYTHONIOENCODING='utf-8'
$env:PYTHONUTF8='1'
conda run -n ai-quant quant-system --help
```
