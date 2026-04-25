# Phase 0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the runnable Phase 0 project foundation for the AI quant research and paper-trading platform.

**Architecture:** Keep Phase 0 small and explicit: settings, logging, risk defaults, CLI, cross-layer plugin interfaces, tests, and docs. No data download, no broker connection, no trading strategy, no Polymarket integration.

**Tech Stack:** Python 3.11+, conda + pip editable install, pandas, numpy, pydantic, pydantic-settings, typer, duckdb, pyarrow, pytest, ruff.

---

## File Structure

- Create `pyproject.toml`: package metadata, dependencies, CLI entry point, pytest and ruff config.
- Create `environment.yml`: conda environment wrapper that installs `.[dev]`.
- Create `.env.example`: safe defaults and comments.
- Create `README.md`: Phase 0 overview, install, run, verify, safety boundaries.
- Create `src/quant_system/__init__.py`: package metadata.
- Create `src/quant_system/cli.py`: Typer CLI with `config show`, `doctor`, and version behavior.
- Create `src/quant_system/config/settings.py`: pydantic settings with default safety controls and live-trading guard.
- Create `src/quant_system/logging/setup.py`: structured JSON logging setup.
- Create `src/quant_system/risk/defaults.py`: reusable risk-limit defaults.
- Create `src/quant_system/core/interfaces.py`: Phase 0 plugin contracts for Factor, Strategy, and PortfolioOptimizer.
- Create package `__init__.py` files.
- Create tests under `tests/`: CLI, settings, logging, risk defaults, and interface contract tests.
- Create docs: `docs/phase_0_learning.md`, `docs/phase_0_execution.md`, `docs/phase_0_architecture.md`.
- Initialize git repository because Phase 0 includes establishing the repo.

## Tasks

### Task 1: Tests and Configuration

- [ ] Write tests first for settings defaults, live guard, risk defaults, logging output, CLI output, and interface definitions.
- [ ] Create `pyproject.toml` and `environment.yml` so tests can run in editable install mode.
- [ ] Run pytest and confirm tests fail because production modules do not exist yet.

### Task 2: Minimal Implementation

- [ ] Implement settings, risk defaults, logging setup, CLI, and core interfaces.
- [ ] Run targeted tests until they pass.
- [ ] Keep live trading disabled by default and require an explicit confirmation phrase if enabled.

### Task 3: Documentation

- [ ] Write README.
- [ ] Write Phase 0 learning, execution, and architecture docs.
- [ ] Include directory tree, commands, success signs, common errors, Mermaid diagram, and handoff to Phase 1.

### Task 4: Verification

- [ ] Run `python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[dev]"`.
- [ ] Run `python -m pytest`.
- [ ] Run `ruff check .`.
- [ ] Run `python -m quant_system.cli --help`.
- [ ] Run `quant-system config show`.
- [ ] Confirm git repository exists and inspect status without reverting user files.
