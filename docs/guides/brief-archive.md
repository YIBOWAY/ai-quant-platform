# Brief Archive Sidebar + Daily Auto-Archive

The morning brief (`/brief`) now ships with a second sidebar column between the
main navigation and the newspaper content. Three tabs — 日报 / 周报 / 月报 —
list archived issues newest-first; clicking a row opens the existing read-only
`/brief/[publicId]` snapshot view. The content area of both pages is unchanged.

## API

`GET /api/brief/archive?locale=zh&months=6`

Returns three group lists:

- `daily`: published daily issues in the last `months` months, grouped by
  calendar month (`key = "2026-08"`).
- `weekly`: **view over daily snapshots** — the last daily issue of each ISO
  week, tagged `kind = "weekly"` with `iso_week = "2026-W32"`, grouped by the
  representative issue's month.
- `monthly`: **view over daily snapshots** — the last daily issue of each
  calendar month, tagged `kind = "monthly"` with `month = "2026-08"`, grouped
  by year.

No rollup rows are stored; weekly/monthly tabs are computed from the same
`brief_issues` rows. Each entry carries `public_id`, `issue_date`, `title`,
and a short `snippet` derived from the stored snapshot lede. When the archive
database is down the route answers 503 and the sidebar renders an honest
"archive unavailable" state — it never fabricates rows.

## Auto-archive CLI

```
.venv/bin/python -m quant_system.cli brief auto-archive [--locale zh] \
    [--base-url http://127.0.0.1:8765]
```

The command collects today's facts from the running local backend (paper
account, equity curve, 3m performance, SPY/QQQ/SOXX/IGV daily bars, Asia
Radar summary, AI news digest, recent runs, options scan status), builds a
`brief_snapshot_v1` payload server-side, and upserts it through
`BriefService` keyed by `(owner, issue_date, locale)` — re-running on the
same day keeps one issue and appends a new snapshot version (idempotent).
Verified against the production Postgres upsert path and mirrored by an
in-memory repository contract test (`tests/test_brief_service.py`); the
frontend export contract test pins the archive response aliases.

Fail-closed: if the paper account, equity curve, or performance master cannot
be read, or the archive database is down, nothing is written and the command
exits non-zero. A reachable-but-malformed blocking payload (e.g. a
performance response without `requested_start`/`requested_end`, or an
explicit `apiError` marker in a 200 body) fails the same way with a typed
`AutoArchiveUnavailable` — never a mid-build crash. A reachable-but-empty
equity curve (fresh account) archives, watermarked `unavailable`. The live
`/brief` page never depends on this job.

Known subset gaps vs. the browser-built payload (the browser "save" button
remains the full-fidelity path):

- `hermes_log` run entries use `kind label · run_id` without the detailed
  metric summaries, and research-candidate entries are not included.
- The Python payload model (the authoritative API contract) has no
  `asia_radar` / `asia_radar_note` fields, so the radar read is folded into
  the lede text only.
- Performance snapshot is stored with the default `selected_range = "7d"`.

## LaunchAgent (macOS)

Template: `scripts/launchd/com.aiquant.brief-auto-archive.plist.template`
(daily 17:20, after the 17:05 `com.aiquant.asia-radar-refresh`). Logs land in
`data/_runtime/logs/brief-auto-archive.launchd.{out,err}.log`.

Install (this renders the plist into `~/Library/LaunchAgents` and bootstraps
it; the repo ships the files but never loads them for you):

```
scripts/install_brief_auto_archive_launchagent.sh
```

Uninstall:

```
launchctl bootout "gui/$(id -u)/com.aiquant.brief-auto-archive"
rm "$HOME/Library/LaunchAgents/com.aiquant.brief-auto-archive.plist"
```

Safety boundary: the job only reads local API facts and writes brief archive
rows. It never places orders and does not touch kill_switch / live_trading /
Gate 1-3 flows.
