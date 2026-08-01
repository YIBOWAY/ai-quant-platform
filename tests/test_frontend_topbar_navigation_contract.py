from pathlib import Path


def test_topbar_is_not_a_second_desktop_navigation() -> None:
    topbar = Path("src/frontend/components/TopBar.tsx").read_text(encoding="utf-8")
    sidebar = Path("src/frontend/components/Sidebar.tsx").read_text(encoding="utf-8")
    nav_config = Path("src/frontend/lib/navConfig.ts").read_text(encoding="utf-8")

    assert "topNavItems" not in topbar
    assert 'href={localizePath("/options-radar", locale)}' not in topbar
    assert "Bell" not in topbar
    assert 'href={localizePath("/backtest", locale)}' not in topbar

    # Routes live in nav SSOT; chrome maps navConfig rather than hardcoding lists.
    assert 'href: "/options-radar"' in nav_config
    assert 'href: "/backtest"' in nav_config
    assert "navSections" in sidebar
    assert "isVisibleOnSurface" in sidebar
    assert "@/lib/navConfig" in sidebar


def test_topbar_mobile_menu_exposes_ai_news() -> None:
    topbar = Path("src/frontend/components/TopBar.tsx").read_text(encoding="utf-8")
    nav_config = Path("src/frontend/lib/navConfig.ts").read_text(encoding="utf-8")

    assert "aiNews" in topbar
    assert 'href: "/ai-news"' in nav_config
    assert "buildNavSections" in topbar
    assert "isVisibleOnSurface" in topbar


def test_topbar_mobile_menu_exposes_sidebar_primary_routes() -> None:
    topbar = Path("src/frontend/components/TopBar.tsx").read_text(encoding="utf-8")
    nav_config = Path("src/frontend/lib/navConfig.ts").read_text(encoding="utf-8")

    expected_routes = [
        'href: "/"',
        'href: "/hermes"',
        'href: "/data-explorer"',
        'href: "/factor-lab"',
        'href: "/backtest"',
        'href: "/strategies"',
        'href: "/experiments"',
        'href: "/paper-trading"',
        'href: "/position-map"',
        'href: "/options-screener"',
        'href: "/options-radar"',
        'href: "/options-tools"',
        'href: "/options-buyside"',
        'href: "/ai-news"',
        'href: "/polymarket"',
        'href: "/agent-studio"',
        'href: "/settings"',
    ]

    for route in expected_routes:
        assert route in nav_config

    assert "@/lib/navConfig" in topbar
    assert "buildNavSections" in topbar
    assert "isVisibleOnSurface" in topbar
    assert "mobileNavSections" in topbar
    assert (
        "max-h-[calc(100dvh-var(--spacing-topbar-height))] overflow-y-auto" in topbar
    )
    assert "key={`${section.name}-${item.href}-${item.name}`}" in topbar
    assert "key={`${section.name}-${item.href}`}" not in topbar
    assert 'href={localizePath("/hermes", locale)}' in topbar


def test_topbar_mobile_menu_exposes_accessible_state() -> None:
    topbar = Path("src/frontend/components/TopBar.tsx").read_text(encoding="utf-8")

    assert 'aria-controls="mobile-navigation"' in topbar
    assert 'id="mobile-navigation"' in topbar
    assert 'aria-current={activePath === item.href ? "page" : undefined}' in topbar
    assert 'window.addEventListener("keydown", onKeyDown)' in topbar
    assert 'event.key === "Escape"' in topbar
    assert "menuButtonRef.current?.focus()" in topbar


def test_expert_research_pages_hidden_from_nav_surfaces() -> None:
    """Factor Lab / Backtester / Experiments: routes kept for audit, nav hidden."""
    nav_config = Path("src/frontend/lib/navConfig.ts").read_text(encoding="utf-8")

    for entry in (
        '{ id: "factorLab", href: "/factor-lab", icon: FlaskConical, surfaces: [] }',
        '{ id: "backtester", href: "/backtest", icon: LineChart, surfaces: [] }',
        '{ id: "experiments", href: "/experiments", icon: Beaker, surfaces: [] }',
    ):
        assert entry in nav_config

    # Data Explorer and Strategy Catalog stay visible (no surfaces override).
    assert '{ id: "dataExplorer", href: "/data-explorer", icon: Database }' in nav_config
    assert '{ id: "replications", href: "/strategies", icon: ScrollText }' in nav_config
