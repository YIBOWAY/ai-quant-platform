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
