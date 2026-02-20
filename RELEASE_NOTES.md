# Release Notes - Advanced Trading Features

## 🟢 Features Implemented
1.  **Regime Adaptive Filter (The Brain)**
    - Uses ADX (Average Directional Index) to detect market regimes:
        - **Trending (Bull/Bear)**: ADX > 25
        - **Volatile/Ranging**: ADX < 20
    - Strategies are now dynamically enabled/disabled based on these regimes.

2.  **Statistical Arbitrage (The Pair Logic)**
    - Added `StatisticalArbitrageStrategy` to `strategy_engine.py`.
    - Implemented simulated Z-Score logic (Price vs VWAP normalized by volatility).
    - Added `statsmodels` dependency for future cointegration features.

3.  **HFT-Lite (Order Slicing)**
    - Created `ExecutionAlgo` to slice large orders (>100 qty) into smaller chunks.
    - Updated `LiveBroker` and `PaperBroker` to process sliced orders.
    - Integrated execution logic into `dashboard_v3.py` Auto-Pilot loop.

## 🛠️ Verification
Please refer to `walkthrough.md` for step-by-step verification instructions.

## 📦 Dependencies
- `statsmodels` (Added to requirements.txt)

## 🚀 Next Steps
- Run the dashboard: `streamlit run ui/dashboard_v3.py`
- Monitor the "Active Strategy Matrix" for regime changes.
- Check "Recent Activity" for HFT-Lite order slicing logs during large trades.
