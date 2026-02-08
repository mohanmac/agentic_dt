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
3.  Select your GitHub repository (`day-trading-bot`).
4.  **Main file path**: Enter `ui/dashboard_v3.py`.
5.  Click **Deploy!**.

## 3. Configure Secrets (CRITICAL)
Your app needs API keys to work. Since we didn't upload `.env`, we must set them in Streamlit Cloud.
1.  On your deployed app dashboard, click **Manage app** (bottom right) -> **⋮ (Settings)** -> **Secrets**.
2.  Paste the following configuration (Update with your REAL keys):

```toml
# .streamlit/secrets.toml

KITE_API_KEY = "your_zerodha_api_key"
KITE_API_SECRET = "your_zerodha_api_secret"
KITE_REDIRECT_URL = "https://your-app-url.streamlit.app"  # Update this after deployment!

# LLM Configuration (Ollama won't work in cloud!)
# Use Google Gemini (Free Tier available) or OpenAI
LLM_PROVIDER = "google"
GOOGLE_API_KEY = "your_google_gemini_key"
GOOGLE_MODEL = "gemini-1.5-pro"

# Trading Settings
DAILY_CAPITAL = 2000
MAX_DAILY_LOSS = 200
MAX_TRADES_PER_DAY = 5
ENABLE_LIVE_TRADING = false
```

## 4. Important Changes for Cloud
*   **Ollama**: Local Ollama **will not work** on Streamlit Cloud. You MUST switch to `LLM_PROVIDER="google"` (Gemini) or OpenAI.
*   **Authentication**:
    *   After deployment, copy your **App URL** (e.g., `https://my-bot.streamlit.app`).
    *   Go to your [Zerodha Developer Console](https://developers.kite.trade/).
    *   Update the **Redirect URL** to your App URL.
*   **Persistence**: Streamlit Cloud restarts your app frequently. The `data/` folder will be reset. Trade history (SQL/JSON) will not persist across reboots unless you use an external database (which is an advanced step).

## 5. Mobile App Conversion
Once your app is live at `https://your-app.streamlit.app`, you can follow the steps to convert it to an Android App:
1.  Go to [PWABuilder.com](https://www.pwabuilder.com).
2.  Enter your Streamlit App URL.
3.  Generate the **Android Store Package**.
4.  Upload to Google Play Console.
