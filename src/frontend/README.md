<div align="center">
<img width="1200" height="475" alt="GHBanner" src="https://github.com/user-attachments/assets/0aa67016-6eaf-458a-adb2-6e31a0763ed6" />
</div>

# Run and deploy your AI Studio app

This contains everything you need to run your app locally.

View your app in AI Studio: https://ai.studio/apps/bd710529-fe5d-48d1-bd85-2de09b5408dd

## Run Locally

**Prerequisites:**  Node.js


1. Install dependencies:
   `npm install`
2. Start the backend API from the repository root:
   `quant-system serve --host 127.0.0.1 --port 8765`
3. Set the API URL in [.env.local](.env.local):
   `NEXT_PUBLIC_QUANT_API_BASE_URL="http://127.0.0.1:8765"`
4. Run the app:
   `npm run dev -- -p 3000`

The current frontend reads real data from the local Phase 9 API. If the backend is
offline, pages render a safe fallback state and show `API OFFLINE` in the safety strip.
