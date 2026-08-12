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
DEFAULT_MODEL = "grok-4.5"
DEFAULT_TIMEOUT_SECONDS = 120.0

_ENV_BASE_URL = "QS_BRIEF_ROLLUP_LLM_BASE_URL"
_ENV_TOKEN = "QS_BRIEF_ROLLUP_LLM_TOKEN"
_ENV_MODEL = "QS_BRIEF_ROLLUP_LLM_MODEL"
_ENV_TIMEOUT = "QS_BRIEF_ROLLUP_LLM_TIMEOUT"

_DRAFT_SYSTEM = {
    "zh": (
        "你是「每日晨报」的财经编辑，负责把一段时期的日报事实汇总成{kind_label}。"
        "硬性规则：只能使用给定事实包中的事实与数字，不得编造任何数字、事件、"
        "引语或结论；每个主题的 item_refs 必须且只能从给定事实包的 item id 列表中选取；"
        "全部数字以事实包中的 stats 与 account_summary 为准，模型不得自行产出数字。"
        "输出必须是一个 JSON 对象，schema 为 "
        "{{\"title\": str, \"main_storyline\": str, "
        "\"topics\": [{{\"title\": str, \"synthesis\": str, \"item_refs\": [str]}}]}}，"
        "其中 topics 数量 3~7 个：main_storyline 概括本期主线，"
        "每个 topic 是一条支线主题及其综合叙述。使用简体中文。"
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
            headers={"accept": "application/json"},
        )
        try:
            try:
                response = http.post(
                    "/v1/chat/completions",
                    json={
                        "model": self._model,
                        "messages": messages,
                        "response_format": {"type": "json_object"},
                    },
                    # The token is only a transport header: it must never end
                    # up in logs, error messages, or the rollup payload.
                    headers={"Authorization": f"Bearer {self._token}"},
                )
            except httpx.HTTPError as exc:
                raise RollupLlmUnavailable(
                    f"rollup LLM request failed: {type(exc).__name__}: {exc}"
                ) from exc
            if response.status_code != 200:
                # Deliberately no response body: it may echo request details.
                raise RollupLlmUnavailable(
                    f"rollup LLM proxy returned HTTP {response.status_code}"
                )
            try:
                envelope = response.json()
            except ValueError as exc:
                raise RollupLlmUnavailable("rollup LLM proxy returned invalid JSON") from exc
        finally:
            if owns_client:
                http.close()

        content = _message_content(envelope)
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


def _message_content(envelope: Any) -> str:
    try:
        content = envelope["choices"][0]["message"]["content"]
    except (TypeError, KeyError, IndexError) as exc:
        raise RollupLlmUnavailable(
            "rollup LLM response is missing choices[0].message.content"
        ) from exc
    if not isinstance(content, str) or not content.strip():
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
    system = _DRAFT_SYSTEM[locale].format(kind_label=kind_label)
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
    system = _CRITIQUE_SYSTEM[locale].format(kind_label=kind_label)
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
