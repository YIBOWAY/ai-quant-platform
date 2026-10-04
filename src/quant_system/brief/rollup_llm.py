"""OpenAI-compatible client for the local Hermes xAI rollup proxy.

Talks to the same local proxy the D-34 worker uses (``{base_url}/v1/chat/completions``)
to draft and critique weekly/monthly brief rollups. Configuration comes from
``QS_BRIEF_ROLLUP_LLM_*`` environment variables; the proxy token is only ever
sent as a request header and is never logged or included in error messages.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://127.0.0.1:8645"
DEFAULT_TOKEN = "local-d34-proxy"
DEFAULT_MODEL = "grok-4.6"
DEFAULT_REASONING_EFFORT = "xhigh"
DEFAULT_TIMEOUT_SECONDS = 300.0

_ENV_BASE_URL = "QS_BRIEF_ROLLUP_LLM_BASE_URL"
_ENV_TOKEN = "QS_BRIEF_ROLLUP_LLM_TOKEN"
_ENV_MODEL = "QS_BRIEF_ROLLUP_LLM_MODEL"
_ENV_TIMEOUT = "QS_BRIEF_ROLLUP_LLM_TIMEOUT"

_NUMBER_STYLE_ZH = (
    "数字排版：金额使用千位分隔并保留两位小数，比例显示百分号并保留两位小数。"
    "account_summary 的 pnl_pct 和 invested_pct 是小数比例，例如 0.0325 应写 3.25%；"
    "stats.period_change_pct 已经是百分数，例如 3.703168 应写 3.70%，不能再次乘100。"
    "正文把 pnl_pct 写为账户盈亏比例、invested_pct 写为已投资比例，禁止直接输出字段名或长小数。"
    "这些仅是既有数字的单位换算和四舍五入，不是新增数字；日期、新闻原始数字和模型版本不改。"
    "缺少市场报价时 valuation_status=incomplete，equity/pnl_abs/pnl_pct/invested_pct 为空；"
    "只能写尚不能计算市值和盈亏，cost_reference_equity 只是含成本价的参考金额，不能写成市值或收益。"
    "现金仍可按给定金额描述。账户总资产变化不等于策略收益，不能忽略入金或不同估值口径。"
)
_NUMBER_STYLE_EN = (
    "Financial formatting: amounts use thousands separators and two decimal places. "
    "account_summary pnl_pct/invested_pct are ratios (0.0325 means 3.25%), while "
    "stats.period_change_pct is already in percent units (3.703168 means 3.70%, never 370.32%). "
    "Use readable labels, not JSON field names or long decimals. Rounding is allowed; "
    "do not alter dates, original news figures or model versions. Incomplete valuation means "
    "market equity/P&L are unknown; cost_reference_equity is not a market valuation or return. "
    "Account equity change is not strategy performance."
)

_DRAFT_SYSTEM = {
    "zh": (
        "你是「每日晨报」的财经编辑，负责把一段时期的日报事实汇总成{kind_label}。"
        "硬性规则：只能使用给定事实包中的事实与数字，不得编造任何数字、事件、"
        "引语或结论；每个主题的 item_refs 必须且只能从给定事实包的 item id 列表中选取；"
        "全部数字以事实包中的 stats 与 account_summary 为准，模型不得自行产出数字。"
        "输出必须是一个 JSON 对象，schema 为 "
        "{{\"title\": str, \"main_storyline\": str, "
        "\"topics\": [{{\"title\": str, \"synthesis\": str, \"item_refs\": [str]}}]}}，"
        "其中 topics 数量 3~7 个：main_storyline 概括本期重要变化，"
        "每个 topic 说明一件具体事情及其依据。使用简体中文。"
        "写给个人读者，用普通中文说明谁发生了什么变化、依据是什么、接下来值得观察什么；"
        "条件不足时明确说尚不能判断，不把推测或关注建议写成事实。"
        "stats.daily_count 是归档日报期数，应写几期日报，不能称作交易日数量。"
        "保留必要的金融术语和原始引用，避免用篮子、抓手、赋能、基座、攻守切换、"
        "资本叙事等借喻代替具体的市场、股票、指标、行为或变化。"
        "例如把前三后三篮子分化写成涨幅前三名与后三名的平均收益差，"
        "谈到算力时具体交代已有的订单、投资或业绩消息。不要写排印、化石等内部称呼。"
    ),
    "en": (
        "You are the editor of the Daily Morning Brief, summarizing a period of "
        "daily issues into a {kind_label}. Hard rules: use only the facts and "
        "numbers in the supplied facts package; never invent numbers, events, "
        "quotes, or conclusions; every topic's item_refs must be chosen "
        "exclusively from the item id list in the facts package; all figures "
        "come from the facts package's stats and account_summary — never "
        "produce numbers yourself. Output must be a single JSON object with "
        "schema {{\"title\": str, \"main_storyline\": str, "
        "\"topics\": [{{\"title\": str, \"synthesis\": str, \"item_refs\": [str]}}]}} "
        "with 3-7 topics: main_storyline captures the period's main thread and "
        "each topic is one secondary storyline with its synthesis. Write in English."
    ),
}

_CRITIQUE_SYSTEM = {
    "zh": (
        "你是「每日晨报」的审核编辑。核对给定{kind_label}草稿："
        "(1) 每个 item_refs 引用是否真实存在于事实包的 item id 列表；"
        "(2) 草稿是否引入了事实包之外的数字、事件或结论；"
        "(3) main_storyline 与 topics 是否一致并覆盖本期主线。"
        "只输出一个 JSON 对象 {{\"ok\": true|false, \"violations\": [str]}}，"
        "violations 逐条列出问题；全部通过时 ok 为 true 且 violations 为空。"
        "使用简体中文。"
    ),
    "en": (
        "You are the reviewing editor of the Daily Morning Brief. Check the "
        "given {kind_label} draft: (1) whether every item_refs reference exists "
        "in the facts package's item id list; (2) whether the draft introduces "
        "numbers, events, or conclusions beyond the facts package; (3) whether "
        "main_storyline and the topics are consistent and cover the period's "
        "main thread. Output a single JSON object "
        "{{\"ok\": true|false, \"violations\": [str]}} listing every problem; "
        "ok is true with empty violations only when all checks pass. "
        "Write in English."
    ),
}

_KIND_LABEL = {
    "zh": {"weekly": "周报", "monthly": "月报"},
    "en": {"weekly": "weekly review", "monthly": "monthly review"},
}


class RollupLlmUnavailable(RuntimeError):
    """Raised when the local rollup LLM proxy cannot produce a usable answer."""


class RollupLlmClient:
    """Two-pass (draft + critique) chat client for brief rollups."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        token: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = (
            base_url
            or os.environ.get(_ENV_BASE_URL, "").strip()
            or DEFAULT_BASE_URL
        ).rstrip("/")
        self._token = (
            token or os.environ.get(_ENV_TOKEN, "").strip() or DEFAULT_TOKEN
        )
        self._model = (
            model or os.environ.get(_ENV_MODEL, "").strip() or DEFAULT_MODEL
        )
        if timeout_seconds is not None:
            self._timeout_seconds = float(timeout_seconds)
        else:
            self._timeout_seconds = _env_timeout()
        self._client = client

    @property
    def model(self) -> str:
        return self._model

    @property
    def reasoning_effort(self) -> str:
        return DEFAULT_REASONING_EFFORT

    @property
    def critic_model(self) -> str:
        # The critique pass uses the same proxied model; kept as a separate
        # provenance field so a split-critic setup stays representable.
        return self._model

    def draft(self, facts: dict[str, Any]) -> dict[str, Any]:
        """Draft the rollup storyline/topics from the facts package."""
        return self._chat_json(_draft_messages(facts))

    def critique(self, facts: dict[str, Any], draft: dict[str, Any]) -> dict[str, Any]:
        """Review a draft; returns ``{"ok": bool, "violations": [str]}``."""
        result = self._chat_json(_critique_messages(facts, draft))
        ok = result.get("ok")
        violations = result.get("violations")
        if (
            not isinstance(ok, bool)
            or not isinstance(violations, list)
            or not all(isinstance(item, str) for item in violations)
        ):
            raise RollupLlmUnavailable(
                "rollup critique payload must be {\"ok\": bool, \"violations\": [str]}"
            )
        return {"ok": ok, "violations": list(violations)}

    def _chat_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        owns_client = self._client is None
        http = self._client or httpx.Client(
            base_url=self._base_url,
            timeout=self._timeout_seconds,
            headers={"accept": "text/event-stream"},
        )
        try:
            try:
                # Long xhigh generations must start receiving upstream data
                # before intermediate connections expire waiting for one JSON
                # response. Collect only answer content, never reasoning text.
                with http.stream(
                    "POST",
                    "/v1/chat/completions",
                    json={
                        "model": self._model,
                        "reasoning_effort": self.reasoning_effort,
                        "messages": messages,
                        "response_format": {"type": "json_object"},
                        "stream": True,
                    },
                    # The token is only a transport header: it must never end
                    # up in logs, error messages, or the rollup payload.
                    headers={"Authorization": f"Bearer {self._token}"},
                ) as response:
                    if response.status_code != 200:
                        # The body may echo request details; never include it.
                        raise RollupLlmUnavailable(
                            f"rollup LLM proxy returned HTTP {response.status_code}"
                        )
                    content = _stream_content(response)
            except httpx.HTTPError as exc:
                raise RollupLlmUnavailable(
                    f"rollup LLM request failed: {type(exc).__name__}: {exc}"
                ) from exc
        finally:
            if owns_client:
                http.close()

        try:
            payload = json.loads(content)
        except ValueError as exc:
            raise RollupLlmUnavailable("rollup LLM message content is not JSON") from exc
        if not isinstance(payload, dict):
            raise RollupLlmUnavailable("rollup LLM message content is not a JSON object")
        return payload


def _env_timeout() -> float:
    raw = os.environ.get(_ENV_TIMEOUT, "").strip()
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        return float(raw)
    except ValueError:
        logger.warning(
            "invalid %s value %r; falling back to %ss",
            _ENV_TIMEOUT,
            raw,
            DEFAULT_TIMEOUT_SECONDS,
        )
        return DEFAULT_TIMEOUT_SECONDS


def _stream_content(response: httpx.Response) -> str:
    chunks: list[str] = []
    finish_reason = None
    done = False
    for line in response.iter_lines():
        if not line.startswith("data:"):
            continue  # SSE comments/keepalives and blank event separators.
        raw = line[5:].strip()
        if raw == "[DONE]":
            done = True
            break
        try:
            event = json.loads(raw)
        except ValueError as exc:
            raise RollupLlmUnavailable("rollup LLM stream returned invalid JSON") from exc
        if not isinstance(event, dict):
            raise RollupLlmUnavailable("rollup LLM stream event is not an object")
        if "error" in event:
            raise RollupLlmUnavailable("rollup LLM stream returned an error event")
        choices = event.get("choices")
        if not isinstance(choices, list):
            raise RollupLlmUnavailable("rollup LLM stream is missing choices")
        for choice in choices:
            if not isinstance(choice, dict) or choice.get("index") != 0:
                raise RollupLlmUnavailable("rollup LLM stream choice is invalid")
            delta = choice.get("delta")
            if not isinstance(delta, dict):
                raise RollupLlmUnavailable("rollup LLM stream delta is invalid")
            content = delta.get("content")
            if content is not None:
                if not isinstance(content, str):
                    raise RollupLlmUnavailable("rollup LLM stream content is invalid")
                chunks.append(content)
            if choice.get("finish_reason") is not None:
                finish_reason = choice["finish_reason"]
    if not done or finish_reason != "stop":
        raise RollupLlmUnavailable("rollup LLM stream generation is incomplete")
    content = "".join(chunks)
    if not content.strip():
        raise RollupLlmUnavailable("rollup LLM message content is empty")
    return content


def _locale_of(facts: dict[str, Any]) -> str:
    return "en" if str(facts.get("locale") or "").strip().lower() == "en" else "zh"


def _facts_json(facts: dict[str, Any]) -> str:
    return json.dumps(facts, ensure_ascii=False, sort_keys=True)


def _draft_messages(facts: dict[str, Any]) -> list[dict[str, str]]:
    locale = _locale_of(facts)
    kind = str(facts.get("kind") or "weekly")
    kind_label = _KIND_LABEL[locale].get(kind, _KIND_LABEL[locale]["weekly"])
    system = _DRAFT_SYSTEM[locale].format(kind_label=kind_label) + (
        _NUMBER_STYLE_ZH if locale == "zh" else _NUMBER_STYLE_EN
    )
    if locale == "en":
        user = (
            "Facts package (JSON). Draft the rollup now; answer with the JSON "
            "object only.\n" + _facts_json(facts)
        )
    else:
        user = "事实包（JSON）。请据此起草，只输出 JSON 对象。\n" + _facts_json(facts)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _critique_messages(facts: dict[str, Any], draft: dict[str, Any]) -> list[dict[str, str]]:
    locale = _locale_of(facts)
    kind = str(facts.get("kind") or "weekly")
    kind_label = _KIND_LABEL[locale].get(kind, _KIND_LABEL[locale]["weekly"])
    system = _CRITIQUE_SYSTEM[locale].format(kind_label=kind_label) + (
        _NUMBER_STYLE_ZH if locale == "zh" else _NUMBER_STYLE_EN
    )
    if locale == "en":
        user = (
            "Facts package (JSON):\n"
            + _facts_json(facts)
            + "\nDraft under review (JSON):\n"
            + json.dumps(draft, ensure_ascii=False, sort_keys=True)
            + "\nAnswer with the verdict JSON object only."
        )
    else:
        user = (
            "事实包（JSON）：\n"
            + _facts_json(facts)
            + "\n待审核草稿（JSON）：\n"
            + json.dumps(draft, ensure_ascii=False, sort_keys=True)
            + "\n只输出审核结论 JSON 对象。"
        )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
