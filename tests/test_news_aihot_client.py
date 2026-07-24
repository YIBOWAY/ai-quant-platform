import httpx
import pytest

from quant_system.news.aihot_client import AiHotClient, AiHotProviderError


def test_items_request_sends_browser_user_agent_and_parses_items() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["params"] = dict(request.url.params.multi_items())
        seen["user_agent"] = request.headers.get("user-agent")
        return httpx.Response(
            200,
            json={
                "count": 1,
                "hasNext": False,
                "nextCursor": None,
                "items": [
                    {
                        "id": "cm9abc456def789ghi012jkl3",
                        "title": "OpenAI 发布新模型",
                        "title_en": "OpenAI releases a new model",
                        "url": "https://example.com/openai",
                        "source": "OpenAI Blog",
                        "publishedAt": "2026-06-28T15:30:00.000Z",
                        "summary": "中文摘要",
                        "category": "ai-models",
                        "score": 0.91,
                        "aiSelected": True,
                        "extraField": "kept in raw",
                    }
                ],
            },
        )

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = AiHotClient(
        base_url="https://aihot.virxact.com/",
        timeout_seconds=1,
        user_agent="UnitTestBrowser/1.0",
        http_client=http_client,
    )

    result = client.items(
        mode="selected",
        category="ai-models",
        q="OpenAI",
        since="2026-06-28T00:00:00Z",
        take=10,
    )

    assert seen == {
        "path": "/api/public/items",
        "params": {
            "mode": "selected",
            "category": "ai-models",
            "q": "OpenAI",
            "since": "2026-06-28T00:00:00Z",
            "take": "10",
        },
        "user_agent": "UnitTestBrowser/1.0",
    }
    assert result.count == 1
    assert result.has_next is False
    assert result.next_cursor is None
    assert result.items[0].id == "cm9abc456def789ghi012jkl3"
    assert result.items[0].published_at == "2026-06-28T15:30:00.000Z"
    assert result.items[0].score == pytest.approx(0.91)
    assert result.items[0].selected is True
    assert result.items[0].raw["extraField"] == "kept in raw"


def test_daily_request_uses_date_path_and_dailies_parses_archive() -> None:
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        if request.url.path == "/api/public/daily/2026-06-28":
            return httpx.Response(
                200,
                json={
                    "date": "2026-06-28",
                    "generatedAt": "2026-06-28T00:01:00.000Z",
                    "windowStart": "2026-06-27T00:00:00.000Z",
                    "windowEnd": "2026-06-28T00:00:00.000Z",
                    "lead": {"title": "今日要点", "leadParagraph": "导语"},
                    "sections": [{"label": "模型发布/更新", "items": []}],
                    "flashes": [{"title": "快讯", "sourceName": "AI HOT"}],
                },
            )
        if request.url.path == "/api/public/dailies":
            return httpx.Response(
                200,
                json={
                    "count": 1,
                    "items": [
                        {
                            "date": "2026-06-28",
                            "generatedAt": "2026-06-28T00:01:00.000Z",
                            "leadTitle": "今日要点",
                        }
                    ],
                },
            )
        raise AssertionError(f"unexpected path {request.url.path}")

    client = AiHotClient(
        base_url="https://aihot.virxact.com",
        timeout_seconds=1,
        user_agent="UnitTestBrowser/1.0",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    daily = client.daily(date="2026-06-28")
    dailies = client.dailies(take=7)

    assert seen_paths == ["/api/public/daily/2026-06-28", "/api/public/dailies"]
    assert daily.date == "2026-06-28"
    assert daily.lead == {"title": "今日要点", "leadParagraph": "导语"}
    assert daily.sections[0]["label"] == "模型发布/更新"
    assert dailies.count == 1
    assert dailies.items[0].lead_title == "今日要点"


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        (httpx.Response(500, json={"error": "upstream failed"}), "aihot_bad_gateway"),
        (httpx.Response(200, text="not-json"), "aihot_invalid_response"),
    ],
)
def test_client_maps_upstream_and_invalid_json_errors(
    response: httpx.Response,
    expected_code: str,
) -> None:
    client = AiHotClient(
        base_url="https://aihot.virxact.com",
        timeout_seconds=1,
        user_agent="UnitTestBrowser/1.0",
        http_client=httpx.Client(transport=httpx.MockTransport(lambda _request: response)),
    )

    with pytest.raises(AiHotProviderError, match=expected_code) as exc_info:
        client.items()

    assert exc_info.value.code == expected_code


def test_client_maps_timeout_errors() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("boom")

    client = AiHotClient(
        base_url="https://aihot.virxact.com",
        timeout_seconds=1,
        user_agent="UnitTestBrowser/1.0",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(AiHotProviderError, match="aihot_timeout") as exc_info:
        client.items()

    assert exc_info.value.status_code == 503
