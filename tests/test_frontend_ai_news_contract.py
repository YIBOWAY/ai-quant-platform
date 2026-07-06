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
    assert 'tone="warning">{text.selectedBadge}</ToneBadge>' not in source
    assert "radial-gradient" not in source
    assert "shadow-[0_24px_80px" not in source


def test_ai_news_view_uses_color_encoded_news_system() -> None:
    source = Path("src/frontend/components/forms/AiNewsView.tsx").read_text(encoding="utf-8")

    assert "categoryToneClass" in source
    assert 'data-ai-news-accent-rail="true"' in source
    assert 'aria-hidden="true"' in source
    assert 'data-ai-news-category-tone' in source
    assert 'data-ai-news-timeline-dot' in source
    assert "aiNewsAccentRailClass" in source
    assert "categoryName(category, locale)" in source
    assert (
        '<ToneBadge tone="neutral">{categoryName(item.category, locale)}</ToneBadge>'
        not in source
    )


def test_ai_news_feed_uses_responsive_cards_before_desktop_table() -> None:
    source = Path("src/frontend/components/forms/AiNewsView.tsx").read_text(encoding="utf-8")

    assert "FeedCardList" in source
    assert "FeedTable" in source
    assert 'data-ai-news-card-list="true"' in source
    assert 'data-ai-news-card="true"' in source
    assert 'className="grid gap-2 lg:hidden"' in source
    assert 'className="hidden lg:block"' in source


def test_ai_news_view_marks_toggle_state_for_assistive_tech() -> None:
    source = Path("src/frontend/components/forms/AiNewsView.tsx").read_text(encoding="utf-8")

    assert 'aria-pressed={tab === item}' in source
    assert 'role="tablist"' not in source
    assert 'role="tab"' not in source
    assert 'aria-pressed={mode === item}' in source
    assert 'aria-pressed={category === item.value}' in source
    assert 'aria-pressed={windowKey === item}' in source


def test_ai_news_toolbar_wraps_filters_on_mobile() -> None:
    source = Path("src/frontend/components/forms/AiNewsView.tsx").read_text(encoding="utf-8")

    assert "mt-2 flex flex-wrap items-center gap-2 pb-1 sm:flex-nowrap sm:overflow-x-auto" in source
    assert "flex min-w-0 flex-wrap gap-2 sm:shrink-0 sm:flex-nowrap" in source
    assert "mt-2 flex items-center gap-2 overflow-x-auto pb-1" not in source


def test_ai_news_view_keeps_mobile_search_available() -> None:
    source = Path("src/frontend/components/forms/AiNewsView.tsx").read_text(encoding="utf-8")

    assert "mobileSearchOpen" in source
    assert 'aria-controls="ai-news-mobile-search"' in source
    assert 'id="ai-news-mobile-search"' in source
    assert 'sm:hidden' in source
    assert 'data-testid="ai-news-search"' in source


def test_ai_news_view_exposes_stable_smoke_selectors() -> None:
    source = Path("src/frontend/components/forms/AiNewsView.tsx").read_text(encoding="utf-8")

    assert 'data-testid="ai-news-root"' in source
    assert 'data-testid="ai-news-readonly-safety"' in source
    assert 'data-testid="ai-news-toolbar"' in source
    assert 'data-testid="ai-news-feed"' in source
    assert 'data-testid="ai-news-original-link"' in source


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
