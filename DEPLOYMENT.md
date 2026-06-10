# 🚀 Streamlit Cloud Deployment Guide

Follow these steps to host your Day Trading Bot on Streamlit Community Cloud (Free).

## 1. Prepare Your GitHub Repository
1.  **Create a new public repository** on GitHub (e.g., `day-trading-bot`).
2.  **Upload your project files** to this repository.
    *   Ensure all files in `DayTradingPaperBot/` are in the root or a subfolder.
    *   **Do NOT upload `.env` or `data/tokens.json`**. (The `.gitignore` file already handles this).

   ```bash
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   # remote add origin <your-repo-url>
   # git push -u origin main
   ```

## 2. Deploy on Streamlit Cloud
1.  Go to [share.streamlit.io](https://share.streamlit.io/).
2.  Click **New app**.
3.  Select repository **`mohanmac/proactive_agentic_dt`**, branch **`main`**.
4.  **Main file path**: `streamlit_app.py` (loads the 12-agent `ui/dashboard.py`).
5.  Click **Deploy!**.

Public URL: **https://proactive-agentic-dt.streamlit.app** (short link may point here).

## 3. Configure Secrets (CRITICAL)
Your app needs API keys to work. Since we did not upload `.env`, set them in Streamlit Cloud.

1.  **Manage app** → **Settings** → **Secrets**.
2.  Paste the template from `.streamlit/secrets.toml.example` and replace placeholders with your real keys.
3.  In [Kite developer console](https://developers.kite.trade/), set **Redirect URL** to the **same** value as `KITE_REDIRECT_URL` (no placeholder URLs).

```toml
KITE_API_KEY = "your_zerodha_api_key"
KITE_API_SECRET = "your_zerodha_api_secret"
KITE_REDIRECT_URL = "https://proactive-agentic-dt.streamlit.app"

LLM_PROVIDER = "openai"
OPENAI_API_KEY = "sk-..."
OPENAI_MODEL = "gpt-4o-mini"

DAILY_CAPITAL = "2000"
MAX_DAILY_LOSS = "200"
MAX_TRADES_PER_DAY = "5"
PER_TRADE_MAX_LOSS_ABSOLUTE = "70"
ENABLE_LIVE_TRADING = "false"
FORCE_EXIT_TIME_HOUR = "15"
FORCE_EXIT_TIME_MINUTE = "15"
```

4.  **Save** Secrets, then **Reboot app**.

## 4. Important Changes for Cloud
*   **Ollama** does not run on Streamlit Cloud — use `LLM_PROVIDER = "openai"` (or Gemini with `GOOGLE_API_KEY`).
*   **Authentication**: `KITE_REDIRECT_URL` must be `https://proactive-agentic-dt.streamlit.app`, not `your-new-app.streamlit.app` or any other placeholder.
*   **Live trading**: keep `ENABLE_LIVE_TRADING = "false"` for dry-runs. Set it to `"true"` only when you are ready for real Zerodha MIS orders, then reboot the app and explicitly turn on Auto-execute in the dashboard.
*   **`.streamlit/config.toml`**: uses `fileWatcherType = "none"` to avoid inotify errors on Cloud.
*   **Persistence**: Streamlit Cloud restarts your app frequently. The `data/` folder will be reset. Trade history (SQL/JSON) will not persist across reboots unless you use an external database (which is an advanced step).

## 5. Mobile App Conversion
Once your app is live at `https://your-app.streamlit.app`, you can follow the steps to convert it to an Android App:
1.  Go to [PWABuilder.com](https://www.pwabuilder.com).
2.  Enter your Streamlit App URL.
3.  Generate the **Android Store Package**.
4.  Upload to Google Play Console.
