# Quant Platform Frontend

This is the local Next.js frontend for the quant research platform.

## Run Locally

**Prerequisites:** Node.js and the backend Python environment.

1. Install dependencies:
   `npm install`
2. Start the backend API from the repository root:
   `quant-system serve --host 127.0.0.1 --port 8765`
3. Set the API URL in [.env.local](.env.local):
   `NEXT_PUBLIC_QUANT_API_BASE_URL="http://127.0.0.1:8765"`
4. Run the app:
   `npm run dev -- --hostname 127.0.0.1 --port 3001`

If Windows refuses to bind the backend on `8765`, start the backend on another
local port and set `NEXT_PUBLIC_QUANT_API_BASE_URL` to that port before starting
the frontend.

Open:

```text
http://127.0.0.1:3001
```

The frontend reads from the local API. If the backend is offline, pages render a
safe fallback state and show `API OFFLINE` in the safety strip.

## Language

The UI is bilingual (English / 中文). The top-bar toggle switches between
locale-prefixed paths such as `/en/options-radar` and `/zh/options-radar`, and
stores the choice in the `qs_lang` cookie for unprefixed paths. Details:
[../../docs/frontend/frontend_chinese_version.md](../../docs/frontend/frontend_chinese_version.md).

## Checks

```powershell
npm run lint
npm run build
$env:PW_E2E="1"
npx playwright test --config playwright.config.ts --workers=1
```

### Hermes Gate 5 release authority

After `npm ci` in this exact directory, run the complete hermetic browser gate
through its single package entry:

```bash
release_root="$(cd ../.. && pwd -P)"
platform_commit="$(git -C "$release_root" rev-parse --verify HEAD)"
gate2_receipt="/absolute/path/to/passing-gate2/backend-non-postgres-receipt.json"
gate2_python="/absolute/path/recorded-as-fresh_environment.path-in-the-passing-Gate-2-receipt/bin/python"
frontend_install_output="/absolute/path/to/a-new-empty-frontend-install-evidence-directory"
gate5_output="/absolute/path/to/a-new-empty-gate5-evidence-directory"
install -d -m 700 "$frontend_install_output" "$gate5_output"
node scripts/prepare-hermes-gate5-install.mjs \
  --expected-commit "$platform_commit" \
  --npm-cli "$(command -v npm)" \
  --output-dir "$frontend_install_output"
frontend_install_receipt="$frontend_install_output/frontend-fresh-install-receipt.json"
npm run test:e2e:gate5 -- \
  --output-dir "$gate5_output" \
  --backend-python "$gate2_python" \
  --gate2-receipt "$gate2_receipt" \
  --frontend-install-receipt "$frontend_install_receipt" \
  --expected-commit "$platform_commit"
```

Both output directories are mandatory. They must already exist, be empty, canonical,
non-symlinked, owned by the current user, and inaccessible to group/other
users. The frontend preparation command runs exact `npm ci` with an owner-only
temporary HOME/cache, removes that temporary state, and binds the current
commit, Node/npm/npx bytes, package inputs, and complete installed
`node_modules` tree. `--backend-python`, `--gate2-receipt`,
`--frontend-install-receipt`, and `--expected-commit` are also mandatory. The
Python must be the retained fresh environment created by the canonical,
passing Gate 2 receipt for that exact commit:
`.tmp/backend-non-postgres-<commit-prefix>-<run-digest>/venv/bin/python`.
Gate 5 rejects a different checkout or environment, a dirty/hidden index,
wrong branch or publication remote, non-Python-3.11, editable/source imports,
an unsuccessful/tampered Gate 2 or frontend install receipt, source/helper,
test-shard, full backend/frontend environment, browser-cache, or
lock/import/interpreter identity mismatch. Its canonical summary records the
commit/tree, receipts and artifact digests, exact safe row environments,
per-row start/end/command/exit/stdout/stderr identities, installer exits,
runtime bytes, noneditable direct URL, module path, and dependency inventory
before any browser row runs. The same sandboxed backend, frontend and
repository authority is collected again after the matrix; any drift fails the
gate.

The command runs, in order, support tests, the provider-free real-backend
smoke, all five combined fixtures, the lifecycle fixture, and rollback. Every
row has unique loopback ports and a unique run ID, uses one worker, forbids
snapshot updates, and validates exact pass/skip counts from TAP or Playwright
JSON. The evidence directory contains only the support TAP, per-row stderr
logs, canonical compact Playwright JSON reports, and the canonical compact
`gate5-summary.json`. Browser reporter stdout is parsed in memory and is never
written as a noncanonical raw report.

Transient HOME, TMPDIR, and XDG cache state lives under the release checkout at
`src/frontend/.tmp/gate5-runtime/<run-token>/`, not in the evidence directory.
The runner records that path in the summary and removes only its exact
owner-marked root after all children close. If a timed-out child does not close
after bounded TERM handling, the runner fails and retains that root for
recovery rather than deleting state that may still be in use.

Gate 5 clears inherited provider, database, reuse-server, custom-backend, and
live-session configuration. `@live-hermes-sessions` is intentionally excluded;
it remains a separately authorized check against an already connected local
Hermes runtime and is not part of this hermetic release command.
