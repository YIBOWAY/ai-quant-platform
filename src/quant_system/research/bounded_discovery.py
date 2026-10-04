"""One frozen, training-only RD-Agent proposal batch; never a research worker.

The normal invocation is a fresh, short-lived evaluation container. RD-Agent's
public convenience method persists the prompt and can issue six auto-continue
requests even with max_retry=1. We therefore instantiate its real APIBackend but
call the one-request completion seam, with content logging/storage disabled.
Nothing in this module evaluates, registers, selects or activates a factor.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import logging
import math
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext, redirect_stderr, redirect_stdout
from datetime import UTC, date, datetime
from fractions import Fraction
from pathlib import Path
from typing import Any, Protocol

from quant_system.d34.qlib_expr import QlibExprError, compile_qlib_expr

MODEL = "openai/grok-4.6"
EFFORT = "xhigh"
MAX_PROPOSALS = 3
RDAGENT_COMMIT = "274e274d5dbb72cc2ea139d1a7c93d73ce9b1198"
METHOD = {
    "rebalance": "monthly_last_observed_session",
    "execution": "next_session_open",
    "selection": "highest_score_top_5_equal_weight_long_only",
    "commission_bps": 1,
    "slippage_bps": 5,
    "cash_interest": 0,
    "universe_membership": "current_static_list_not_point_in_time",
}
_STAT_FIELDS = {
    "id",
    "expression",
    "observations",
    "rank_ic",
    "ic_ir",
    "sharpe",
    "annualized_return",
    "max_drawdown",
}
_SYMBOL = re.compile(r"[A-Z][A-Z0-9.\-]{0,15}\Z")
_IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{0,79}\Z")
_SYSTEM = """You propose a small, frozen set of financial research hypotheses.
Return ONLY a JSON object with 'proposals': a list of 1 to 3 objects, each with
exactly 'title', 'expression', 'rationale'. Write title/rationale in clear Chinese.
The input contains statistics from the declared recent research window, up to
its supplied completed-data cutoff. Treat available history as research data,
not an unseen holdout. Only observations after a strategy is frozen can supply
new forward evidence. Propose all hypotheses now; there will be NO refinement
after observing later results. Do not invent returns, Sharpe, probabilities or
backtest claims. Rationale explains an economic hypothesis, not proven profit.
The universe is a fixed present-day stock list and has survivorship bias. It is
NOT a historical index and you cannot add, remove or select its members.
Use the exact supplied monthly, next-open, long-only, Top-5, 1bp+5bp protocol.
The expression is a score; HIGHER means more attractive. No code, files, imports,
web requests or narrative outside the requested JSON. Do not repeat an existing
factor expression or return a constant. Consider distinct mechanisms, not three
window tweaks of the same formula. Supported fields: $open,$high,$low,$close,$volume.
Supported operators: +,-,*,/ and unary minus. Supported unary functions: Abs,Log,Sign.
Supported two-argument functions: Ref,Mean,Std,Sum,Max,Min,Delta,EMA,Rank; the second
argument MUST be an integer 1 through 252. Rank is a rolling time-series rank,
not cross-sectional rank. Numeric literals MUST be integers 1 through 252; no
decimals or literal zero. Limit every expression to 400 characters, depth 6 and
24 expression nodes. Ref only uses positive lags: never future prices.
"""


class DiscoveryError(ValueError):
    """Only a fixed code, never provider exception messages or prompt content."""


class CompletionBackend(Protocol):
    def _create_chat_completion_inner_function(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> tuple[str, str | None]: ...


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def proposal_protocol_digest() -> str:
    """Formatting/refactors must not request new hypotheses after test results."""
    return _digest(
        {
            "system": _SYSTEM,
            "model": MODEL,
            "effort": EFFORT,
            "method": METHOD,
            "rdagent_commit": RDAGENT_COMMIT,
        }
    )


def _training_input(facts: dict) -> dict:
    # A strict, small schema prevents accidentally passing a full evaluation
    # report (which contains validation/test performance) into the model.
    if not isinstance(facts, dict) or set(facts) != {
        "training_start",
        "training_end",
        "universe",
        "factor_statistics",
    }:
        raise DiscoveryError("training_facts_schema_invalid")
    try:
        start = date.fromisoformat(facts["training_start"])
        end = date.fromisoformat(facts["training_end"])
    except (TypeError, ValueError):
        raise DiscoveryError("training_dates_invalid") from None
    if not start < end < date.today():
        raise DiscoveryError("training_dates_invalid")
    symbols = facts["universe"]
    if (
        not isinstance(symbols, list)
        or not 5 <= len(symbols) <= 100
        or any(not isinstance(s, str) or not _SYMBOL.fullmatch(s) for s in symbols)
        or len(set(symbols)) != len(symbols)
    ):
        raise DiscoveryError("training_universe_invalid")
    stats = facts["factor_statistics"]
    if not isinstance(stats, list) or not 1 <= len(stats) <= 30:
        raise DiscoveryError("training_statistics_invalid")
    clean = []
    identifiers = set()
    for item in stats:
        if not isinstance(item, dict) or set(item) - _STAT_FIELDS:
            raise DiscoveryError("training_statistics_invalid")
        identifier = item.get("id")
        if (
            not isinstance(identifier, str)
            or not _IDENTIFIER.fullmatch(identifier)
            or identifier in identifiers
        ):
            raise DiscoveryError("training_statistics_invalid")
        identifiers.add(identifier)
        observations = item.get("observations")
        if type(observations) is not int or not 1 <= observations <= 10_000_000:
            raise DiscoveryError("training_statistics_invalid")
        normalized = {"id": identifier, "observations": observations}
        for key in sorted(_STAT_FIELDS - {"id", "expression", "observations"}):
            value = item.get(key)
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value)):
                raise DiscoveryError("training_statistics_invalid")
            normalized[key] = value
        expression = item.get("expression")
        if expression is not None:
            try:
                expression = compile_qlib_expr(expression).qlib
            except (QlibExprError, TypeError, AttributeError):
                raise DiscoveryError("training_expression_invalid") from None
        normalized["expression"] = expression
        clean.append(normalized)
    return {**facts, "universe": list(symbols), "factor_statistics": clean}


def _symbolic(node: ast.AST) -> tuple[str, Fraction | None]:
    """Detect literal/algebraic constants without executing model text.

    Canonicalization also catches whitespace/parenthesis and simple commutative
    duplicates. Equal predictions from different formulas are checked later by
    the numerical evaluator; this deliberately is not a full symbolic engine.
    """
    if isinstance(node, ast.Constant):
        value = Fraction(node.value)
        return str(value), value
    if isinstance(node, ast.Name):
        return node.id, None
    if isinstance(node, ast.UnaryOp):
        name, value = _symbolic(node.operand)
        return f"-({name})", -value if value is not None else None
    if isinstance(node, ast.Call):
        arguments = [_symbolic(argument) for argument in node.args]
        name = f"{node.func.id}({','.join(a[0] for a in arguments)})"
        if not all(a[1] is not None for a in arguments):
            return name, None
        value = arguments[0][1]
        function = node.func.id
        if function in {"Delta", "Std"}:
            value = Fraction(0)
        elif function == "Sum":
            value *= arguments[1][1]
        elif function == "Abs":
            value = abs(value)
        elif function == "Sign":
            value = Fraction((value > 0) - (value < 0))
        elif function == "Log":
            value = Fraction(str(math.log(max(float(value), 1e-12))))
        elif function == "Rank":
            window = arguments[1][1]
            value = (window + 1) / (2 * window)
        return name, value
    left, lv = _symbolic(node.left)
    right, rv = _symbolic(node.right)
    op = type(node.op)
    if op is ast.Sub and left == right:
        return "0", Fraction(0)
    if op is ast.Div and left == right:
        return "1", Fraction(1)
    if op is ast.Mult and (lv == 0 or rv == 0):
        return "0", Fraction(0)
    if op is ast.Div and lv == 0:
        return "0", Fraction(0)
    if lv is not None and rv is not None:
        try:
            value = {
                ast.Add: lambda: lv + rv,
                ast.Sub: lambda: lv - rv,
                ast.Mult: lambda: lv * rv,
                ast.Div: lambda: lv / rv,
            }[op]()
        except ZeroDivisionError:
            raise DiscoveryError("constant_expression") from None
        return str(value), value
    if op in (ast.Add, ast.Mult):
        left, right = sorted((left, right))
    return f"{op.__name__}({left},{right})", None


def _expression_identity(expression: str) -> tuple[str, bool]:
    pythonish = re.sub(r"\$([a-z]+)", r"field_\1", expression)
    identity, value = _symbolic(ast.parse(pythonish, mode="eval").body)
    return identity, value is not None


def _proposals(response: str, facts: dict) -> list[dict]:
    try:
        parsed = json.loads(response)
    except (ValueError, TypeError):
        raise DiscoveryError("response_invalid_json") from None
    if not isinstance(parsed, dict) or set(parsed) != {"proposals"}:
        raise DiscoveryError("response_schema_invalid")
    raw = parsed["proposals"]
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_PROPOSALS:
        raise DiscoveryError("proposal_limit_invalid")
    seen = {
        _expression_identity(item["expression"])[0]
        for item in facts["factor_statistics"]
        if item["expression"]
    }
    result = []
    for index, proposal in enumerate(raw, 1):
        record = {
            "id": f"rdagent_proposal_{index}",
            "title": None,
            "expression": None,
            "rationale": None,
            "status": "rejected",
            "reason": None,
        }
        if (
            not isinstance(proposal, dict)
            or set(proposal) != {"title", "expression", "rationale"}
            or any(
                not isinstance(proposal[key], str) or not proposal[key].strip()
                for key in ("title", "expression", "rationale")
            )
            or len(proposal.get("title", "")) > 100
            or len(proposal.get("rationale", "")) > 1500
        ):
            record["reason"] = "proposal_schema_invalid"
            result.append(record)
            continue
        record.update({key: proposal[key].strip() for key in ("title", "rationale")})
        expression = proposal["expression"].strip()
        # Keep rejected expressions for review, but bound their size.
        record["expression"] = expression[:400]
        try:
            compiled = compile_qlib_expr(expression)
            identity, constant = _expression_identity(compiled.qlib)
            record["expression"] = compiled.qlib
            if constant:
                record["reason"] = "constant_expression"
            elif identity in seen:
                record["reason"] = "duplicate_expression"
            else:
                record.update(status="frozen", lookback=compiled.lookback)
            seen.add(identity)
        except QlibExprError as exc:
            record["reason"] = exc.code
        except DiscoveryError as exc:
            record["reason"] = str(exc)
        result.append(record)
    return result


def _exclusive_json(path: Path, payload: dict) -> None:
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, allow_nan=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())


@contextmanager
def _rdagent_backend() -> Iterator[CompletionBackend]:
    """Container-only: silence BOTH text and object sinks before APIBackend()."""
    if os.environ.get("LITELLM_CHAT_MODEL") != MODEL:
        raise DiscoveryError("model_must_be_grok46")
    if os.environ.get("LITELLM_REASONING_EFFORT") != EFFORT:
        raise DiscoveryError("reasoning_must_be_xhigh")
    if any(
        name.startswith("LITELLM_") and name.endswith(("_KEY", "_SECRET", "_TOKEN"))
        for name in os.environ
    ):
        raise DiscoveryError("logged_secret_configuration_forbidden")
    commit = Path("/opt/rdagent/.hqa-upstream-commit").read_text().strip()
    if commit != RDAGENT_COMMIT:
        raise DiscoveryError("rdagent_version_mismatch")
    os.environ.update(
        {
            "LITELLM_CHAT_STREAM": "true",
            "LITELLM_LOG_LLM_CHAT_CONTENT": "false",
            "LOG_LLM_CHAT_CONTENT": "false",
            "MAX_RETRY": "1",
            "LITELLM_MAX_RETRY": "1",
            "USE_CHAT_CACHE": "false",
            "DUMP_CHAT_CACHE": "false",
            "LITELLM_USE_CHAT_CACHE": "false",
            "LITELLM_DUMP_CHAT_CACHE": "false",
            "LOG_STORAGES": "{}",
            "LITELLM_CHAT_MODEL_MAP": "{}",
        }
    )
    os.environ.pop("LOG_UI_SERVER_PORT", None)
    previous_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        with open(os.devnull, "w") as discard, redirect_stdout(discard), redirect_stderr(discard):
            import rdagent.log as rdlog
            from rdagent.oai.llm_conf import LLM_SETTINGS

            logger = rdlog.rdagent_logger
            old_object, old_log = logger.log_object, logger._log
            # loguru.remove() alone does not disable FileStorage.log(). These
            # methods are the verified sinks for settings, prompts and response.
            logger.log_object = lambda *args, **kwargs: None
            logger._log = lambda *args, **kwargs: None
            try:
                import litellm
                from rdagent.oai.backend.litellm import LITELLM_SETTINGS
                from rdagent.oai.llm_utils import APIBackend

                litellm.set_verbose = False
                litellm.suppress_debug_info = True
                litellm.telemetry = False
                litellm.callbacks = []
                litellm.success_callback = []
                litellm.failure_callback = []
                litellm.cache = None
                for settings in (LLM_SETTINGS, LITELLM_SETTINGS):
                    settings.max_retry = 1
                    settings.log_llm_chat_content = False
                    settings.dump_chat_cache = settings.use_chat_cache = False
                    settings.dump_embedding_cache = settings.use_embedding_cache = False
                    settings.chat_model_map = {}
                if (
                    LITELLM_SETTINGS.chat_model != MODEL
                    or LITELLM_SETTINGS.reasoning_effort != EFFORT
                    or not LITELLM_SETTINGS.chat_stream
                    or LLM_SETTINGS.backend != "rdagent.oai.backend.LiteLLMAPIBackend"
                ):
                    raise DiscoveryError("backend_configuration_mismatch")
                yield APIBackend(
                    use_chat_cache=False,
                    dump_chat_cache=False,
                    use_embedding_cache=False,
                    dump_embedding_cache=False,
                )
            finally:
                logger.log_object, logger._log = old_object, old_log
    finally:
        logging.disable(previous_logging)


def _execute(facts: dict, output: Path, backend: CompletionBackend | None) -> dict:
    clean = _training_input(facts)
    output.parent.mkdir(parents=True, exist_ok=True)
    marker = output.with_suffix(output.suffix + ".attempt.json")
    metadata = {
        "schema_version": 1,
        "model": MODEL,
        "reasoning_effort": EFFORT,
        "adapter": "rdagent.oai.llm_utils.APIBackend:single_completion",
        "rdagent_commit": RDAGENT_COMMIT,
        "facts_digest": _digest(clean),
        "methodology": METHOD,
        "training_start": clean["training_start"],
        "training_end": clean["training_end"],
        "evaluation_scope": "retrospective_research_then_forward_observation",
        "generated_at": datetime.now(UTC).isoformat(),
        "attempts": 1,
        "evaluation_status": "not_evaluated",
        "proposals": [],
    }
    if output.exists():
        raise DiscoveryError("output_already_exists")
    try:
        _exclusive_json(marker, {**metadata, "status": "attempt_reserved"})
    except FileExistsError:
        raise DiscoveryError("attempt_already_reserved") from None
    messages = [
        {"role": "system", "content": _SYSTEM},
        {
            "role": "user",
            "content": json.dumps(
                {"training_facts": clean, "methodology": METHOD},
                ensure_ascii=False,
                allow_nan=False,
            ),
        },
    ]
    try:
        with _rdagent_backend() if backend is None else nullcontext(backend) as actual:
            response, finish = actual._create_chat_completion_inner_function(
                messages=messages,
                response_format={"type": "json_object"},
                timeout=300,
            )
        if finish != "stop":
            raise DiscoveryError("response_incomplete")
        metadata["proposals"] = _proposals(response, clean)
        metadata["status"] = "frozen"
        metadata["response_digest"] = hashlib.sha256(response.encode()).hexdigest()
    except DiscoveryError as exc:
        metadata.update(status="failed", error=str(exc))
    except Exception:
        metadata.update(status="failed", error="provider_or_runtime_error")
    metadata["proposals_digest"] = _digest(metadata["proposals"])
    _exclusive_json(output, metadata)
    return metadata


def propose_hypotheses(
    training_facts: dict,
    output_dir: Path,
    *,
    backend: CompletionBackend | None = None,
) -> dict:
    """Freeze at most three proposals after exactly one request, never retry.

    ``backend`` is an injectable sealed-test seam; production callers leave it
    unset and run this module in the pinned RD-Agent evaluation image. Once an
    attempt is reserved, reusing its output location cannot call the model again.
    """
    return _execute(training_facts, Path(output_dir) / "proposals.json", backend)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        facts = json.loads(arguments.facts.read_text(encoding="utf-8"))
        result = _execute(facts, arguments.output, None)
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "attempts": result["attempts"],
                    "proposals_digest": result["proposals_digest"],
                    "error": result.get("error"),
                }
            )
        )
        return 0 if result["status"] == "frozen" else 1
    except DiscoveryError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
    except Exception:
        print(json.dumps({"status": "failed", "error": "discovery_input_or_output_error"}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
