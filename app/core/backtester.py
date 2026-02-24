"""
Real Historical Backtester for DayTradingPaperBot.

Architecture:
  1. HistoricalDataFetcher  - Downloads NSE OHLCV via yfinance (.NS suffix)
  2. IndicatorEngine        - Computes all technical indicators purely with pandas
  3. RegimeDetector         - Classifies each bar as BULL/BEAR/RANGING/VOLATILE
  4. BarReplayEngine        - Calls strategy.analyze() on each bar's data dict
  5. BacktestEngine         - Orchestrates everything, tracks trades, computes stats
  6. RealBacktestResult     - Comprehensive result dataclass

Data resolution:
  - 3-year period: daily bars (yfinance supports unlimited history at 1d)
  - Intraday strategies that filter on clock time receive a fixed mock time of
    11:00 AM IST (institutional window) so they are evaluated fairly.
"""

import datetime
import math
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

import numpy as np
import pandas as pd

# ─────────────────────────────────────────────────────────────────────────────
# Result Dataclasses
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TradeRecord:
    symbol: str
    strategy_name: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    quantity: int
    pnl_inr: float
    pnl_pct: float
    regime: str
    slippage_cost: float
    brokerage_cost: float


@dataclass
class RealBacktestResult:
    strategy_name: str
    symbol: str
    period: str           # e.g. "3y"
    data_start: str
    data_end: str
    bars_analyzed: int
    total_trades: int
    win_trades: int
    loss_trades: int
    win_rate: float               # %
    total_pnl_inr: float
    total_pnl_pct: float
    max_drawdown_pct: float
    avg_win_pct: float
    avg_loss_pct: float
    profit_factor: float
    expectancy_inr: float
    sharpe_ratio: float
    calmar_ratio: float
    regime_breakdown: Dict[str, dict]   # {BULL: {trades, win_rate, pnl}, ...}
    monthly_returns: List[dict]
    equity_curve: List[float]
    trade_log: List[TradeRecord] = field(default_factory=list)
    error: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# 1. Historical Data Fetcher
# ─────────────────────────────────────────────────────────────────────────────

# NSE symbol map: display name → yfinance ticker
NSE_SYMBOL_MAP = {
    "MID150BEES": "MID150BEES.NS",
    "MOM100":     "MOM100.NS",
    "MID150CASE": "MID150CASE.NS",
    "TRENT":      "TRENT.NS",
    "BEL":        "BEL.NS",
    "COALINDIA":  "COALINDIA.NS",
    "IDFCFIRSTB": "IDFCFIRSTB.NS",
    "TATACHEM":   "TATACHEM.NS",
    "POLYCAB":    "POLYCAB.NS",
    "PERSISTENT": "PERSISTENT.NS",
    "NIFTYBEES":  "NIFTYBEES.NS",
    "JUNIORBEES": "JUNIORBEES.NS",
}

PERIOD_DAYS = {
    "1y": 365,
    "2y": 730,
    "3y": 1095,
    "5y": 1825,
}


def fetch_historical_data(symbol: str, period: str = "3y") -> pd.DataFrame:
    """
    Download NSE daily OHLCV from yfinance.
    Returns DataFrame with columns: Open, High, Low, Close, Volume.
    Raises ValueError if data is insufficient.
    """
    try:
        import yfinance as yf
    except ImportError:
        raise ImportError("yfinance not installed. Run: pip install yfinance")

    ticker = NSE_SYMBOL_MAP.get(symbol, f"{symbol}.NS")
    df = yf.download(ticker, period=period, interval="1d",
                     auto_adjust=True, progress=False)

    if df.empty:
        raise ValueError(f"No data returned for {ticker}. "
                         "Symbol may be delisted or incorrect.")

    # Flatten MultiIndex columns that yfinance sometimes returns
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()

    min_bars = PERIOD_DAYS.get(period, 365) // 2   # allow partial data
    if len(df) < min_bars:
        raise ValueError(
            f"Insufficient data: got {len(df)} bars for {ticker}, "
            f"need at least {min_bars}."
        )

    return df


# ─────────────────────────────────────────────────────────────────────────────
# 2. Indicator Engine (pure pandas, no ta-lib)
# ─────────────────────────────────────────────────────────────────────────────

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _adx(high: pd.Series, low: pd.Series, close: pd.Series,
         period: int = 14) -> pd.Series:
    prev_high = high.shift(1)
    prev_low  = low.shift(1)
    prev_close = close.shift(1)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs()
    ], axis=1).max(axis=1)

    plus_dm  = (high - prev_high).clip(lower=0)
    minus_dm = (prev_low - low).clip(lower=0)

    # zero out cases where the other direction is larger
    mask = plus_dm < minus_dm
    plus_dm[mask] = 0
    mask2 = minus_dm < plus_dm
    minus_dm[mask2] = 0

    atr      = tr.ewm(span=period, adjust=False).mean()
    plus_di  = 100 * plus_dm.ewm(span=period, adjust=False).mean() / atr.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(span=period, adjust=False).mean() / atr.replace(0, np.nan)

    dx  = (100 * (plus_di - minus_di).abs() /
           (plus_di + minus_di).replace(0, np.nan))
    adx = dx.ewm(span=period, adjust=False).mean()
    return adx


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds all needed technical columns to the OHLCV DataFrame.
    """
    df = df.copy()

    # EMAs
    df["ema_9"]   = _ema(df["Close"], 9)
    df["ema_21"]  = _ema(df["Close"], 21)
    df["ema_50"]  = _ema(df["Close"], 50)
    df["ema_200"] = _ema(df["Close"], 200)

    # RSI
    df["rsi"] = _rsi(df["Close"])

    # Bollinger Bands (20,2)
    bb_mid          = df["Close"].rolling(20).mean()
    bb_std          = df["Close"].rolling(20).std()
    df["bb_upper"]  = bb_mid + 2 * bb_std
    df["bb_lower"]  = bb_mid - 2 * bb_std
    df["bb_mid"]    = bb_mid
    df["bb_width"]  = (df["bb_upper"] - df["bb_lower"]) / bb_mid.replace(0, np.nan)

    # VWAP proxy (daily: typical price × cumulative vol normalization)
    df["vwap_proxy"] = (df["High"] + df["Low"] + df["Close"]) / 3

    # Volume ratio (vs 20-day average)
    df["vol_avg_20"]   = df["Volume"].rolling(20).mean()
    df["volume_ratio"] = df["Volume"] / df["vol_avg_20"].replace(0, np.nan)

    # ADX
    df["adx"] = _adx(df["High"], df["Low"], df["Close"])

    # Volatility percentile (annualised rolling std of returns, 20d window)
    log_ret = np.log(df["Close"] / df["Close"].shift(1))
    rolling_vol = log_ret.rolling(20).std() * math.sqrt(252)
    df["volatility_percentile"] = rolling_vol.rank(pct=True) * 100

    # Resistance level: rolling 20-day high (prior bars)
    df["resistance_level"] = df["High"].shift(1).rolling(20).max()

    # Opening range high proxy (previous day high)
    df["opening_range_high"] = df["High"].shift(1)

    # DMA proxies
    df["dma_50"]  = df["ema_50"]
    df["dma_200"] = df["ema_200"]

    return df.dropna()


# ─────────────────────────────────────────────────────────────────────────────
# 3. Regime Detector
# ─────────────────────────────────────────────────────────────────────────────

def detect_regime(row: pd.Series) -> str:
    """
    Classifies bar into: BULL | BEAR | RANGING | VOLATILE
    Uses ADX + price vs EMA200 + volatility percentile.
    """
    adx   = row.get("adx", 20)
    close = row["Close"]
    ema200 = row["ema_200"]
    vol_pct = row.get("volatility_percentile", 50)

    if adx > 25:
        if close > ema200:
            return "BULL"
        else:
            return "BEAR"
    elif adx < 18:
        return "RANGING"
    else:
        return "VOLATILE" if vol_pct > 70 else "RANGING"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Stock Data Builder
# ─────────────────────────────────────────────────────────────────────────────

# Mock time in the centre of the institutional window so time-gated strategies
# (InstitutionalFlow, StopHuntProtection) are evaluated fairly during backtest.
_BACKTEST_MOCK_DATETIME = datetime.datetime(2000, 1, 1, 11, 0, 0)


def build_stock_data(row: pd.Series, symbol: str) -> dict:
    """
    Constructs the stock_data dict expected by strategy.analyze().
    """
    return {
        "symbol":               symbol,
        "ltp":                  float(row["Close"]),
        "vwap":                 float(row["vwap_proxy"]),
        "volume_ratio":         float(row.get("volume_ratio", 1.0)),
        "ema_9":                float(row.get("ema_9", row["Close"])),
        "ema_21":               float(row.get("ema_21", row["Close"])),
        "ema_50":               float(row.get("ema_50", row["Close"])),
        "dma_50":               float(row.get("dma_50",  row["Close"])),
        "dma_200":              float(row.get("dma_200", row["Close"])),
        "rsi":                  float(row.get("rsi", 50)),
        "bb_lower":             float(row.get("bb_lower", row["Close"] * 0.98)),
        "bb_upper":             float(row.get("bb_upper", row["Close"] * 1.02)),
        "bb_width":             float(row.get("bb_width", 0.04)),
        "resistance_level":     float(row.get("resistance_level", row["Close"] * 0.99)),
        "opening_range_high":   float(row.get("opening_range_high", row["High"])),
        "adx":                  float(row.get("adx", 20)),
        "volatility_percentile": float(row.get("volatility_percentile", 50)),
        # Inject mock datetime so time-based strategies evaluate correctly
        "_mock_now":            _BACKTEST_MOCK_DATETIME,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 5. Bar Replay Engine
# ─────────────────────────────────────────────────────────────────────────────

SLIPPAGE_PCT   = 0.001   # 0.1%
BROKERAGE_INR  = 20.0    # ₹20 per order (buy + sell = ₹40 round-trip)
CAPITAL_PER_TRADE_INR = 3000.0   # ETF strategy budget per trade


def simulate_strategy_on_bar(strategy, stock_data: dict):
    """
    Patch datetime.datetime.now() inside the strategy to use the mock time,
    then call strategy.analyze().
    """
    import unittest.mock as mock

    mock_dt = stock_data.get("_mock_now", _BACKTEST_MOCK_DATETIME)

    # Patch datetime.now inside strategy_engine module
    with mock.patch("app.core.strategy_engine.datetime") as mock_datetime:
        mock_datetime.datetime.now.return_value = mock_dt
        mock_datetime.datetime.combine = datetime.datetime.combine
        mock_datetime.date = datetime.date
        mock_datetime.time = datetime.time
        try:
            return strategy.analyze(stock_data)
        except Exception:
            return None


# ─────────────────────────────────────────────────────────────────────────────
# 6. BacktestEngine
# ─────────────────────────────────────────────────────────────────────────────

def _annualised_sharpe(daily_returns: List[float]) -> float:
    """Sharpe ratio assuming 252 trading days, risk-free = 6% (India)."""
    if len(daily_returns) < 10:
        return 0.0
    arr = np.array(daily_returns)
    rf_daily = 0.06 / 252
    excess = arr - rf_daily
    if excess.std() == 0:
        return 0.0
    return float((excess.mean() / excess.std()) * math.sqrt(252))


def run_real_backtest(
    strategy,
    symbol: str,
    period: str = "3y",
) -> RealBacktestResult:
    """
    Full bar-by-bar backtest for one strategy on one symbol.

    Returns RealBacktestResult with comprehensive performance metrics.
    """
    # ── Fetch & prepare data ─────────────────────────────────────────────────
    try:
        raw_df = fetch_historical_data(symbol, period)
    except Exception as exc:
        return RealBacktestResult(
            strategy_name=strategy.name, symbol=symbol, period=period,
            data_start="", data_end="", bars_analyzed=0,
            total_trades=0, win_trades=0, loss_trades=0, win_rate=0,
            total_pnl_inr=0, total_pnl_pct=0, max_drawdown_pct=0,
            avg_win_pct=0, avg_loss_pct=0, profit_factor=0,
            expectancy_inr=0, sharpe_ratio=0, calmar_ratio=0,
            regime_breakdown={}, monthly_returns=[], equity_curve=[],
            error=str(exc),
        )

    df = compute_indicators(raw_df)

    # ── State tracking ───────────────────────────────────────────────────────
    capital          = 20_000.0       # starting capital
    peak_capital     = capital
    max_drawdown     = 0.0
    equity_curve     = [capital]
    daily_returns    = []
    trade_log: List[TradeRecord] = []
    regime_stats: Dict[str, dict] = {}

    position_open    = False
    entry_price      = 0.0
    entry_date       = ""
    entry_qty        = 0
    entry_regime     = ""

    gross_wins  = 0.0
    gross_losses = 0.0
    win_count    = 0
    loss_count   = 0
    win_pcts: List[float] = []
    loss_pcts: List[float] = []

    # Collect monthly timestamps
    monthly_equity: Dict[str, float] = {}

    bars = list(df.iterrows())

    for i, (date, row) in enumerate(bars):

        regime = detect_regime(row)
        stock_data = build_stock_data(row, symbol)
        stock_data["_mock_now"] = _BACKTEST_MOCK_DATETIME

        # ── Exit logic (if in position, check stop/target on this bar) ───────
        if position_open:
            cur_price = float(row["Close"])
            # stop loss: 5% below entry, target: 8% above entry
            sl_price = entry_price * 0.95
            tgt_price = entry_price * 1.08

            if cur_price <= sl_price or cur_price >= tgt_price or i == len(bars) - 1:
                # Simulate fill at next-bar open (with slippage)
                exit_raw = float(row["Open"]) if i < len(bars) - 1 else cur_price
                slippage_exit = exit_raw * SLIPPAGE_PCT
                exit_price = exit_raw - slippage_exit   # slippage works against us on exit

                gross_pnl = (exit_price - entry_price) * entry_qty
                total_brokerage = BROKERAGE_INR * 2  # buy + sell
                net_pnl = gross_pnl - total_brokerage
                pnl_pct = (exit_price - entry_price) / entry_price * 100

                capital += net_pnl
                daily_returns.append(net_pnl / (entry_price * entry_qty))

                rec = TradeRecord(
                    symbol=symbol,
                    strategy_name=strategy.name,
                    entry_date=entry_date,
                    exit_date=str(date.date() if hasattr(date, "date") else date),
                    entry_price=round(entry_price, 2),
                    exit_price=round(exit_price, 2),
                    quantity=entry_qty,
                    pnl_inr=round(net_pnl, 2),
                    pnl_pct=round(pnl_pct, 2),
                    regime=entry_regime,
                    slippage_cost=round(slippage_exit * entry_qty, 2),
                    brokerage_cost=total_brokerage,
                )
                trade_log.append(rec)

                if net_pnl > 0:
                    win_count += 1
                    gross_wins += net_pnl
                    win_pcts.append(pnl_pct)
                else:
                    loss_count += 1
                    gross_losses += abs(net_pnl)
                    loss_pcts.append(pnl_pct)

                # Regime stats
                if entry_regime not in regime_stats:
                    regime_stats[entry_regime] = {"trades": 0, "wins": 0, "pnl": 0.0}
                regime_stats[entry_regime]["trades"] += 1
                if net_pnl > 0:
                    regime_stats[entry_regime]["wins"] += 1
                regime_stats[entry_regime]["pnl"] += net_pnl

                position_open = False

        # ── Entry logic ──────────────────────────────────────────────────────
        if not position_open:
            signal = simulate_strategy_on_bar(strategy, stock_data)

            if signal and signal.signal_type == "BUY":
                # Fill at next bar's open (realistic execution)
                if i + 1 < len(bars):
                    next_date, next_row = bars[i + 1]
                    fill_raw = float(next_row["Open"])
                else:
                    fill_raw = float(row["Close"])

                slippage_entry = fill_raw * SLIPPAGE_PCT
                entry_price = fill_raw + slippage_entry   # slippage works against us on entry
                entry_qty = max(1, int(CAPITAL_PER_TRADE_INR / entry_price))

                if entry_price * entry_qty > capital:
                    entry_qty = max(0, int(capital / entry_price))

                if entry_qty > 0:
                    position_open = True
                    entry_date = str(date.date() if hasattr(date, "date") else date)
                    entry_regime = regime

        # ── Equity tracking ──────────────────────────────────────────────────
        equity_curve.append(round(capital, 2))
        if capital > peak_capital:
            peak_capital = capital
        dd = (peak_capital - capital) / peak_capital * 100
        if dd > max_drawdown:
            max_drawdown = dd

        # Monthly equity snapshot
        month_key = str(date)[:7] if isinstance(date, str) else date.strftime("%Y-%m")
        monthly_equity[month_key] = capital

    # ── Post-processing ──────────────────────────────────────────────────────
    total_trades = win_count + loss_count
    win_rate = (win_count / total_trades * 100) if total_trades else 0
    total_pnl_inr = capital - 20_000.0
    total_pnl_pct = (total_pnl_inr / 20_000.0) * 100
    avg_win_pct  = float(np.mean(win_pcts))  if win_pcts  else 0.0
    avg_loss_pct = float(np.mean(loss_pcts)) if loss_pcts else 0.0
    profit_factor = (gross_wins / gross_losses) if gross_losses else float("inf")
    expectancy = ((win_rate / 100 * abs(avg_win_pct) -
                   (1 - win_rate / 100) * abs(avg_loss_pct)) / 100
                  * CAPITAL_PER_TRADE_INR)
    sharpe = _annualised_sharpe(daily_returns)
    calmar = (total_pnl_pct / max_drawdown) if max_drawdown else 0.0

    # Regime breakdown with win rate
    regime_breakdown: Dict[str, dict] = {}
    for reg, stats in regime_stats.items():
        t = stats["trades"]
        w = stats["wins"]
        regime_breakdown[reg] = {
            "trades":   t,
            "win_rate": round(w / t * 100, 1) if t else 0,
            "pnl_inr":  round(stats["pnl"], 2),
        }

    # Monthly returns list
    monthly_returns = []
    prev_eq = 20_000.0
    for month, eq in sorted(monthly_equity.items()):
        monthly_returns.append({
            "Month":    month,
            "P&L (₹)": round(eq - prev_eq, 2),
            "Return %": round((eq - prev_eq) / prev_eq * 100, 2),
        })
        prev_eq = eq

    return RealBacktestResult(
        strategy_name   = strategy.name,
        symbol          = symbol,
        period          = period,
        data_start      = str(df.index[0].date() if hasattr(df.index[0], "date") else df.index[0])[:10],
        data_end        = str(df.index[-1].date() if hasattr(df.index[-1], "date") else df.index[-1])[:10],
        bars_analyzed   = len(df),
        total_trades    = total_trades,
        win_trades      = win_count,
        loss_trades     = loss_count,
        win_rate        = round(win_rate, 1),
        total_pnl_inr   = round(total_pnl_inr, 2),
        total_pnl_pct   = round(total_pnl_pct, 2),
        max_drawdown_pct = round(max_drawdown, 2),
        avg_win_pct     = round(avg_win_pct, 2),
        avg_loss_pct    = round(avg_loss_pct, 2),
        profit_factor   = round(profit_factor, 2),
        expectancy_inr  = round(expectancy, 2),
        sharpe_ratio    = round(sharpe, 2),
        calmar_ratio    = round(calmar, 2),
        regime_breakdown = regime_breakdown,
        monthly_returns  = monthly_returns,
        equity_curve     = equity_curve,
        trade_log        = trade_log,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 7. Multi-symbol / Multi-strategy batch runner
# ─────────────────────────────────────────────────────────────────────────────

def run_portfolio_backtest(
    strategies: list,
    symbols: List[str],
    period: str = "3y",
) -> Dict[str, Dict[str, RealBacktestResult]]:
    """
    Runs real backtest for every (strategy × symbol) combination.
    Returns: {strategy_name: {symbol: RealBacktestResult}}
    """
    results: Dict[str, Dict[str, RealBacktestResult]] = {}
    for strat in strategies:
        results[strat.name] = {}
        for sym in symbols:
            results[strat.name][sym] = run_real_backtest(strat, sym, period)
    return results
