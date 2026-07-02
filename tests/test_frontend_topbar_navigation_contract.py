from pathlib import Path


def test_topbar_is_not_a_second_desktop_navigation() -> None:
    topbar = Path("src/frontend/components/TopBar.tsx").read_text(encoding="utf-8")
    sidebar = Path("src/frontend/components/Sidebar.tsx").read_text(encoding="utf-8")

    assert "topNavItems" not in topbar
    assert 'href={localizePath("/options-radar", locale)}' not in topbar
    assert "Bell" not in topbar
    assert 'href={localizePath("/backtest", locale)}' not in topbar

    assert "/options-radar" in sidebar
    assert "/backtest" in sidebar


def test_topbar_mobile_menu_exposes_ai_news() -> None:
    topbar = Path("src/frontend/components/TopBar.tsx").read_text(encoding="utf-8")

    assert "aiNews" in topbar
    assert 'href: "/ai-news"' in topbar


def test_topbar_mobile_menu_exposes_accessible_state() -> None:
    topbar = Path("src/frontend/components/TopBar.tsx").read_text(encoding="utf-8")

    assert 'aria-controls="mobile-navigation"' in topbar
    assert 'id="mobile-navigation"' in topbar
    assert 'aria-current={activePath === item.href ? "page" : undefined}' in topbar
