from pathlib import Path


def test_sidebar_links_to_ai_news_page() -> None:
    sidebar = Path("src/frontend/components/Sidebar.tsx").read_text(encoding="utf-8")

    assert "Newspaper" in sidebar
    assert "aiNews" in sidebar
    assert 'href: "/ai-news"' in sidebar


def test_ai_news_page_uses_dedicated_view_component() -> None:
    page = Path("src/frontend/app/ai-news/page.tsx")

    assert page.is_file()
    assert "AiNewsView" in page.read_text(encoding="utf-8")


def test_ai_news_view_uses_timeline_not_form_sidebar() -> None:
    source = Path("src/frontend/components/forms/AiNewsView.tsx").read_text(encoding="utf-8")

    assert "TimelineArticle" in source
    assert "groupFeedItems" in source
    assert "grid-cols-[320px_1fr]" not in source
    assert "bg-accent-success px-4 py-2" not in source


def test_ai_news_view_uses_terminal_surface_style() -> None:
    source = Path("src/frontend/components/forms/AiNewsView.tsx").read_text(encoding="utf-8")

    assert "bg-bg-base" in source
    assert "bg-bg-surface" in source
    assert "radial-gradient" not in source
    assert "shadow-[0_24px_80px" not in source


def test_ai_news_view_debounces_search_and_supports_load_more() -> None:
    source = Path("src/frontend/components/forms/AiNewsView.tsx").read_text(encoding="utf-8")

    assert "useDebouncedValue" in source
    assert "debouncedKeyword" in source
    assert "loadMore" in source
    assert "next_cursor" in source


def test_ai_news_daily_lead_is_optional() -> None:
    source = Path("src/frontend/components/forms/AiNewsView.tsx").read_text(encoding="utf-8")

    assert "daily.lead ? (" in source
    assert "daily.lead" in source


def test_ai_news_view_prefers_chinese_summary_over_english_title() -> None:
    source = Path("src/frontend/components/forms/AiNewsView.tsx").read_text(encoding="utf-8")

    assert 'const summary = item.summary || item.title_en || "";' in source
    assert 'const summary = item.title_en || item.summary || "";' not in source


def test_ai_news_view_surfaces_operational_warnings() -> None:
    source = Path("src/frontend/components/forms/AiNewsView.tsx").read_text(encoding="utf-8")

    assert "OperationalWarningStrip" in source
    assert "operationalWarnings" in source
    assert "external beta source" in source


def test_ai_news_view_sanitizes_external_links() -> None:
    source = Path("src/frontend/components/forms/AiNewsView.tsx").read_text(encoding="utf-8")

    assert "safeExternalUrl" in source
    assert 'url.protocol === "http:" || url.protocol === "https:"' in source
    assert "href={item.url}" not in source
    assert "href={sourceUrl}" not in source
