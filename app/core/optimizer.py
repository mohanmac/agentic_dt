"""
Strategy & Guardrail Self-Optimizer for DayTradingPaperBot.

Workflow:
  1. Run full portfolio backtest (all strategies × all symbols, 3y real data)
  2. Analyze results to compute optimal parameters analytically
  3. Apply optimizations to live strategy_engine + risk_engine
  4. Return a detailed OptimizationReport for display in the dashboard

Optimizable parameters:
  Strategy-level:
    - Enable / disable strategies (based on profitability & Sharpe)
    - Strategy priority rank (used as tiebreaker in ensemble)
    - Per-regime confidence weighting

  Guardrail-level (RiskConfig + MULTI_TF_CONFIG):
    - min_confluence_strategies
    - max_consecutive_losses
    - avoid_first_minutes
    - trailing_stop_activation_percent
    - max_capital_per_trade
    - max_loss_per_day
"""

import datetime
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.core.backtester import (
    RealBacktestResult,
    run_portfolio_backtest,
    NSE_SYMBOL_MAP,
)


# ─────────────────────────────────────────────────────────────────────────────
# Result Dataclasses
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class StrategyProfile:
    name: str
    symbols_tested: int
    avg_win_rate: float          # %
    avg_profit_factor: float
    avg_sharpe: float
    avg_max_drawdown: float      # %
    avg_total_trades: float
    best_regime: str             # BULL / BEAR / RANGING / VOLATILE
    worst_regime: str
    recommendation: str          # KEEP / DISABLE / PRIORITIZE
    weight: float                # 0.0 – 1.0, used in ensemble


@dataclass
class GuardrailChange:
    parameter: str
    old_value: Any
    new_value: Any
    reason: str


@dataclass
class OptimizationReport:
    run_at: datetime.datetime
    period: str
    symbols: List[str]
    strategies_tested: int
    total_bars_analyzed: int
    total_trades_analyzed: int

    # Per-strategy findings
    strategy_profiles: List[StrategyProfile]

    # Strategies the optimizer decided to disable / prioritize
    disabled_strategies: List[str]
    prioritized_strategies: List[str]

    # Guardrail changes (with before/after values)
    guardrail_changes: List[GuardrailChange]

    # Human-readable change log
    changes_applied: List[str]

    # Forward-looking impact estimate
    estimated_win_rate_improvement: float   # delta %
    estimated_drawdown_reduction: float     # delta %
    estimated_quality_score: float          # 0–100


# ─────────────────────────────────────────────────────────────────────────────
# Core Optimizer
# ─────────────────────────────────────────────────────────────────────────────

class StrategyOptimizer:
    """
    Runs the full backtest suite and self-adjusts strategy + guardrail parameters.
    All changes are applied in-place on the live engine objects and
    the strategy_engine.py MULTI_TF_CONFIG dict.
    """

    # Thresholds for disabling a strategy
    MIN_WIN_RATE_TO_KEEP    = 38.0  # %
    MIN_PROFIT_FACTOR       = 0.90
    MIN_SHARPE_TO_PRIORITIZE = 0.30
    MIN_WIN_RATE_PRIORITIZE  = 50.0

    # Guardrail bounds
    MIN_CONFLUENCE = 2
    MAX_CONFLUENCE = 5
    MIN_FIRST_AVOIDANCE = 0     # minutes
    MAX_FIRST_AVOIDANCE = 30
    MIN_CONSEC_LOSSES   = 2
    MAX_CONSEC_LOSSES   = 5
    MAX_CAPITAL_FLOOR   = 1500.0
    MAX_CAPITAL_CEILING = 5000.0

    def __init__(self, strategy_engine, risk_engine):
        self.strategy_engine = strategy_engine
        self.risk_engine     = risk_engine

    # ── Step 1: Run Full Backtests ─────────────────────────────────────────

    def run_backtests(
        self,
        symbols: List[str],
        period: str = "3y",
        progress_callback=None,
    ) -> Dict[str, Dict[str, RealBacktestResult]]:
        """
        Runs portfolio backtest for every strategy × every symbol.
        Returns: {strategy_name: {symbol: RealBacktestResult}}
        """
        strategies = self.strategy_engine.strategies
        total = len(strategies) * len(symbols)
        done  = 0

        all_results: Dict[str, Dict[str, RealBacktestResult]] = {}

        for strat in strategies:
            all_results[strat.name] = {}
            for sym in symbols:
                result = __import__(
                    "app.core.backtester", fromlist=["run_real_backtest"]
                ).run_real_backtest(strat, sym, period)
                all_results[strat.name][sym] = result
                done += 1
                if progress_callback:
                    progress_callback(done / total, strat.name, sym)

        return all_results

    # ── Step 2: Analyse Results ────────────────────────────────────────────

    def _aggregate_strategy(
        self,
        strat_name: str,
        sym_results: Dict[str, RealBacktestResult],
    ) -> StrategyProfile:
        """Compute average KPIs across all symbols for one strategy."""
        valid = [r for r in sym_results.values() if not r.error and r.total_trades > 0]

        if not valid:
            return StrategyProfile(
                name=strat_name, symbols_tested=0,
                avg_win_rate=0, avg_profit_factor=0, avg_sharpe=0,
                avg_max_drawdown=100, avg_total_trades=0,
                best_regime="N/A", worst_regime="N/A",
                recommendation="DISABLE", weight=0.0,
            )

        avg_wr  = statistics.mean(r.win_rate          for r in valid)
        avg_pf  = statistics.mean(
            min(r.profit_factor, 10.0)                # cap inf at 10
            for r in valid
        )
        avg_sh  = statistics.mean(r.sharpe_ratio      for r in valid)
        avg_dd  = statistics.mean(r.max_drawdown_pct  for r in valid)
        avg_tr  = statistics.mean(r.total_trades       for r in valid)

        # Regime aggregation: collect all regime P&Ls across symbols
        regime_pnl: Dict[str, float] = {}
        for r in valid:
            for reg, stats in r.regime_breakdown.items():
                regime_pnl[reg] = regime_pnl.get(reg, 0.0) + stats["pnl_inr"]

        best_regime  = max(regime_pnl,  key=regime_pnl.get)  if regime_pnl else "N/A"
        worst_regime = min(regime_pnl,  key=regime_pnl.get)  if regime_pnl else "N/A"

        # Recommendation logic
        if avg_wr < self.MIN_WIN_RATE_TO_KEEP or avg_pf < self.MIN_PROFIT_FACTOR:
            rec = "DISABLE"
            weight = 0.0
        elif avg_sh >= self.MIN_SHARPE_TO_PRIORITIZE and avg_wr >= self.MIN_WIN_RATE_PRIORITIZE:
            rec = "PRIORITIZE"
            # Weight proportional to Sharpe (normalised to 0–1 range)
            weight = min(1.0, avg_sh / 2.0)
        else:
            rec = "KEEP"
            weight = min(1.0, max(0.1, avg_sh))

        return StrategyProfile(
            name=strat_name,
            symbols_tested=len(valid),
            avg_win_rate=round(avg_wr, 1),
            avg_profit_factor=round(avg_pf, 2),
            avg_sharpe=round(avg_sh, 2),
            avg_max_drawdown=round(avg_dd, 2),
            avg_total_trades=round(avg_tr, 1),
            best_regime=best_regime,
            worst_regime=worst_regime,
            recommendation=rec,
            weight=round(weight, 2),
        )

    def _derive_optimal_confluence(
        self, profiles: List[StrategyProfile]
    ) -> Tuple[int, str]:
        """
        Optimal confluence = number of KEEP/PRIORITIZE strategies with
        avg_win_rate >= 50%, rounded up, clipped to [MIN, MAX].
        Logic: the more reliable strategies you have, the more you can
               afford to wait for them to agree.
        """
        reliable = [
            p for p in profiles
            if p.recommendation != "DISABLE" and p.avg_win_rate >= 50.0
        ]
        if not reliable:
            return self.MIN_CONFLUENCE, "No reliable strategies found; using minimum."

        # We want at least 30% of reliable strategies to agree
        suggested = max(self.MIN_CONFLUENCE, round(len(reliable) * 0.35))
        suggested = min(suggested, self.MAX_CONFLUENCE)

        reason = (
            f"{len(reliable)} reliable strategies (WR≥50%). "
            f"Requiring {suggested} to agree ensures quality entries."
        )
        return suggested, reason

    def _derive_optimal_first_avoidance(
        self, all_results: Dict[str, Dict[str, RealBacktestResult]]
    ) -> Tuple[int, str]:
        """
        Look at regime_breakdown: if VOLATILE regime makes up the majority
        of losing trades in the first part of the day, increase avoidance.
        Keep it simple: use 15 minutes as the data-validated sweet spot
        (matches what NSE literature suggests). We confirm via avg drawdown.
        """
        avg_dd_all = []
        for sym_res in all_results.values():
            for r in sym_res.values():
                if not r.error:
                    avg_dd_all.append(r.max_drawdown_pct)

        if not avg_dd_all:
            return 15, "Using default 15 min (no data)."

        avg_dd = statistics.mean(avg_dd_all)
        if avg_dd > 12.0:
            minutes = 30
            reason = (
                f"High avg max-drawdown ({avg_dd:.1f}%) across strategies. "
                "Extending first-bar avoidance to 30 minutes to reduce opening noise."
            )
        elif avg_dd > 7.0:
            minutes = 15
            reason = (
                f"Moderate avg max-drawdown ({avg_dd:.1f}%). "
                "Maintaining 15-minute first-bar avoidance."
            )
        else:
            minutes = 0
            reason = (
                f"Low avg max-drawdown ({avg_dd:.1f}%). "
                "Opening range is manageable; removing avoidance window."
            )
        return minutes, reason

    def _derive_optimal_consec_losses(
        self, profiles: List[StrategyProfile]
    ) -> Tuple[int, str]:
        """
        If average win rate is low, reduce allowed consecutive losses
        to preserve capital faster.
        """
        valid = [p for p in profiles if p.recommendation != "DISABLE"]
        if not valid:
            return 3, "All strategies disabled; using conservative default."

        avg_wr = statistics.mean(p.avg_win_rate for p in valid)

        if avg_wr < 45.0:
            n = 2
            reason = f"Low avg win rate ({avg_wr:.1f}%). Early halt at {n} losses protects capital."
        elif avg_wr < 55.0:
            n = 3
            reason = f"Moderate win rate ({avg_wr:.1f}%). Halt at {n} consecutive losses."
        else:
            n = 4
            reason = f"High win rate ({avg_wr:.1f}%). Can tolerate {n} consecutive losses."
        return n, reason

    def _derive_optimal_capital(
        self, profiles: List[StrategyProfile]
    ) -> Tuple[float, str]:
        """
        Optimal capital per trade = expectancy-weighted, bounded by safety limits.
        If avg profit factor < 1.2, reduce risk per trade.
        """
        valid = [p for p in profiles if p.recommendation != "DISABLE"]
        if not valid:
            return 2000.0, "No profitable strategies. Using minimum capital."

        avg_pf = statistics.mean(p.avg_profit_factor for p in valid)
        avg_wr = statistics.mean(p.avg_win_rate for p in valid)

        if avg_pf >= 1.5 and avg_wr >= 55.0:
            capital = 4000.0
            reason = (
                f"High profit factor ({avg_pf:.2f}) & win rate ({avg_wr:.1f}%). "
                "Increasing capital per trade to ₹4,000."
            )
        elif avg_pf >= 1.2:
            capital = 3000.0
            reason = (
                f"Good profit factor ({avg_pf:.2f}). "
                "Maintaining capital per trade at ₹3,000."
            )
        else:
            capital = 2000.0
            reason = (
                f"Low profit factor ({avg_pf:.2f}). "
                "Reducing capital per trade to ₹2,000 for safety."
            )
        return capital, reason

    def _derive_trailing_stop(
        self, all_results: Dict[str, Dict[str, RealBacktestResult]]
    ) -> Tuple[float, str]:
        """Trailing stop activation = 1.5× average win percentage."""
        win_pcts = []
        for sym_res in all_results.values():
            for r in sym_res.values():
                if not r.error and r.avg_win_pct > 0:
                    win_pcts.append(r.avg_win_pct)

        if not win_pcts:
            return 2.0, "Default trailing stop activation at 2.0%."

        avg_win = statistics.mean(win_pcts)
        activation = round(max(1.0, min(5.0, avg_win * 0.60)), 1)
        reason = (
            f"Average win = {avg_win:.2f}%. "
            f"Trailing stop activates at {activation}% ({avg_win:.2f}% × 60%)."
        )
        return activation, reason

    # ── Step 3: Apply Optimizations ───────────────────────────────────────

    def _apply_guardrail_changes(
        self, changes: List[GuardrailChange]
    ) -> List[str]:
        """Apply computed guardrail changes to live engine objects."""
        import app.core.strategy_engine as se_module

        applied = []
        for ch in changes:
            try:
                if ch.parameter == "min_confluence_strategies":
                    se_module.MULTI_TF_CONFIG["gates"]["min_confluence_strategies"] = ch.new_value
                    applied.append(
                        f"✅ min_confluence: {ch.old_value} → {ch.new_value}"
                    )
                elif ch.parameter == "avoid_first_minutes":
                    self.risk_engine.config.avoid_first_minutes = ch.new_value
                    applied.append(
                        f"✅ avoid_first_minutes: {ch.old_value} → {ch.new_value}"
                    )
                elif ch.parameter == "max_consecutive_losses":
                    self.risk_engine.config.max_consecutive_losses = ch.new_value
                    applied.append(
                        f"✅ max_consecutive_losses: {ch.old_value} → {ch.new_value}"
                    )
                elif ch.parameter == "max_capital_per_trade":
                    self.risk_engine.config.max_capital_per_trade = ch.new_value
                    applied.append(
                        f"✅ max_capital_per_trade: ₹{ch.old_value:,.0f} → ₹{ch.new_value:,.0f}"
                    )
                elif ch.parameter == "trailing_stop_activation_percent":
                    self.risk_engine.config.trailing_stop_activation_percent = ch.new_value
                    applied.append(
                        f"✅ trailing_stop_activation: {ch.old_value}% → {ch.new_value}%"
                    )
            except Exception as exc:
                applied.append(f"⚠️ Failed to apply {ch.parameter}: {exc}")
        return applied

    def _apply_strategy_changes(
        self,
        profiles: List[StrategyProfile],
        disabled: List[str],
        prioritized: List[str],
    ) -> List[str]:
        """Enable/disable strategies in the live strategy engine."""
        applied = []
        for p in profiles:
            if p.name in disabled:
                self.strategy_engine.active_strategies[p.name] = False
                applied.append(f"🔴 Disabled  {p.name} (WR={p.avg_win_rate:.1f}%, PF={p.avg_profit_factor:.2f})")
            elif p.name in prioritized:
                self.strategy_engine.active_strategies[p.name] = True
                applied.append(f"🟢 Prioritized  {p.name} (WR={p.avg_win_rate:.1f}%, Sharpe={p.avg_sharpe:.2f})")
            else:
                self.strategy_engine.active_strategies[p.name] = True
                applied.append(f"🟡 Kept  {p.name} (WR={p.avg_win_rate:.1f}%, PF={p.avg_profit_factor:.2f})")
        return applied

    # ── Master Entry Point ─────────────────────────────────────────────────

    def optimize(
        self,
        symbols: List[str],
        period: str = "3y",
        progress_callback=None,
    ) -> OptimizationReport:
        """
        Full optimization pipeline:
          1. Backtest all strategies × all symbols
          2. Derive optimal parameters
          3. Apply changes to live engines
          4. Return OptimizationReport
        """
        import app.core.strategy_engine as se_module

        # ── 1. Run backtests ─────────────────────────────────────────────
        all_results = self.run_backtests(symbols, period, progress_callback)

        # ── 2. Build per-strategy profiles ───────────────────────────────
        profiles: List[StrategyProfile] = []
        total_bars    = 0
        total_trades  = 0

        for strat_name, sym_res in all_results.items():
            profile = self._aggregate_strategy(strat_name, sym_res)
            profiles.append(profile)
            for r in sym_res.values():
                if not r.error:
                    total_bars   += r.bars_analyzed
                    total_trades += r.total_trades

        disabled_strategies    = [p.name for p in profiles if p.recommendation == "DISABLE"]
        prioritized_strategies = [p.name for p in profiles if p.recommendation == "PRIORITIZE"]

        # ── 3. Derive optimal guardrail values ───────────────────────────
        old_config = self.risk_engine.config
        old_confluence = se_module.MULTI_TF_CONFIG["gates"]["min_confluence_strategies"]

        new_confluence, r_confluence = self._derive_optimal_confluence(profiles)
        new_avoidance,  r_avoidance  = self._derive_optimal_first_avoidance(all_results)
        new_consec,     r_consec     = self._derive_optimal_consec_losses(profiles)
        new_capital,    r_capital    = self._derive_optimal_capital(profiles)
        new_trailing,   r_trailing   = self._derive_trailing_stop(all_results)

        guardrail_changes: List[GuardrailChange] = [
            GuardrailChange(
                "min_confluence_strategies",
                old_confluence,
                new_confluence,
                r_confluence,
            ),
            GuardrailChange(
                "avoid_first_minutes",
                old_config.avoid_first_minutes,
                new_avoidance,
                r_avoidance,
            ),
            GuardrailChange(
                "max_consecutive_losses",
                old_config.max_consecutive_losses,
                new_consec,
                r_consec,
            ),
            GuardrailChange(
                "max_capital_per_trade",
                old_config.max_capital_per_trade,
                new_capital,
                r_capital,
            ),
            GuardrailChange(
                "trailing_stop_activation_percent",
                old_config.trailing_stop_activation_percent,
                new_trailing,
                r_trailing,
            ),
        ]

        # ── 4. Apply changes ─────────────────────────────────────────────
        strat_changes   = self._apply_strategy_changes(profiles, disabled_strategies, prioritized_strategies)
        guard_changes   = self._apply_guardrail_changes(guardrail_changes)
        changes_applied = strat_changes + guard_changes

        # ── 5. Estimate improvement ───────────────────────────────────────
        kept_profiles = [p for p in profiles if p.recommendation != "DISABLE"]
        prev_avg_wr   = statistics.mean(p.avg_win_rate     for p in profiles) if profiles else 0
        new_avg_wr    = statistics.mean(p.avg_win_rate     for p in kept_profiles) if kept_profiles else 0
        prev_avg_dd   = statistics.mean(p.avg_max_drawdown for p in profiles) if profiles else 0
        new_avg_dd    = statistics.mean(p.avg_max_drawdown for p in kept_profiles) if kept_profiles else 0

        win_improvement = round(new_avg_wr - prev_avg_wr, 1)
        dd_reduction    = round(prev_avg_dd - new_avg_dd, 1)

        # Quality score: composite of Sharpe, win rate, drawdown, profit factor
        valid_profiles = [p for p in kept_profiles if p.avg_sharpe is not None]
        if valid_profiles:
            avg_sharpe = statistics.mean(p.avg_sharpe for p in valid_profiles)
            avg_pf     = statistics.mean(p.avg_profit_factor for p in valid_profiles)
            quality    = min(100.0, (
                new_avg_wr * 0.40 +
                min(avg_pf, 3.0) / 3.0 * 30 +
                min(avg_sharpe, 2.0) / 2.0 * 20 +
                max(0, (20.0 - new_avg_dd) / 20.0) * 10
            ))
        else:
            quality = 0.0

        return OptimizationReport(
            run_at=datetime.datetime.now(),
            period=period,
            symbols=symbols,
            strategies_tested=len(profiles),
            total_bars_analyzed=total_bars,
            total_trades_analyzed=total_trades,
            strategy_profiles=profiles,
            disabled_strategies=disabled_strategies,
            prioritized_strategies=prioritized_strategies,
            guardrail_changes=guardrail_changes,
            changes_applied=changes_applied,
            estimated_win_rate_improvement=win_improvement,
            estimated_drawdown_reduction=dd_reduction,
            estimated_quality_score=round(quality, 1),
        )


# ─────────────────────────────────────────────────────────────────────────────
# Adaptive Optimizer — Trade-by-Trade Continuous Learning
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class LiveTradeRecord:
    strategy_name: str
    symbol: str
    won: bool
    pnl_pct: float
    pnl_inr: float
    regime: str          # BULL / BEAR / RANGING / VOLATILE
    trade_number: int
    timestamp: datetime.datetime = field(default_factory=datetime.datetime.now)


@dataclass
class MicroOptimizationEvent:
    trade_number: int
    timestamp: datetime.datetime
    trigger: str         # TRADE_WIN / TRADE_LOSS / STREAK / QUALITY_DROP
    changes: List[str]
    new_quality_score: float
    new_confluence: int
    active_strategies: List[str]


class AdaptiveOptimizer:
    """
    Continuous learning optimizer that:
    1. Records every live trade outcome (O(1) per trade)
    2. After every trade, runs a fast micro-optimization (< 10ms)
    3. Every FULL_BACKTEST_INTERVAL trades, triggers a full 3-year backtest
    4. Blends historical (70%) + live (30%) signals for parameter decisions
    5. Auto-applies all changes to the live engines instantly
    """

    FULL_BACKTEST_INTERVAL = 5       # run full backtest every N live trades
    MIN_LIVE_TRADES_FOR_SIGNAL = 2   # need at least this many trades before adjusting
    QUALITY_DROP_THRESHOLD   = 40.0  # trigger immediate reoptimize if quality < this

    # Learning rate: how much weight to give live trades vs historical backtest
    LIVE_WEIGHT   = 0.35
    HIST_WEIGHT   = 0.65

    def __init__(self, strategy_engine, risk_engine):
        self.strategy_engine = strategy_engine
        self.risk_engine     = risk_engine

        # Live trade log
        self.live_trades: List[LiveTradeRecord] = []

        # Per-strategy live running stats
        # {strategy_name: {trades, wins, total_pnl, regimes: {BULL: {t, w}, ...}}}
        self.live_stats: Dict[str, dict] = {}

        # Event log (displayed in dashboard)
        self.optimization_events: List[MicroOptimizationEvent] = []

        # Cached historical backtest report (set after full backtest)
        self.historical_report: Optional[OptimizationReport] = None

        # Quality tracking
        self.current_quality_score: float = 50.0
        self.consecutive_losses: int = 0
        self.consecutive_wins: int = 0

    # ── Live Stats Update ──────────────────────────────────────────────────

    def record_trade(
        self,
        strategy_name: str,
        symbol: str,
        won: bool,
        pnl_pct: float,
        pnl_inr: float,
        regime: str = "UNKNOWN",
    ) -> MicroOptimizationEvent:
        """
        Called after every trade closes.
        Records the outcome and triggers micro-optimization.
        Returns the optimization event for display.
        """
        trade_num = len(self.live_trades) + 1
        record = LiveTradeRecord(
            strategy_name=strategy_name,
            symbol=symbol,
            won=won,
            pnl_pct=pnl_pct,
            pnl_inr=pnl_inr,
            regime=regime,
            trade_number=trade_num,
        )
        self.live_trades.append(record)

        # Update per-strategy stats
        if strategy_name not in self.live_stats:
            self.live_stats[strategy_name] = {
                "trades": 0, "wins": 0, "total_pnl": 0.0,
                "regimes": {}
            }
        s = self.live_stats[strategy_name]
        s["trades"] += 1
        s["total_pnl"] += pnl_inr
        if won:
            s["wins"] += 1
        if regime not in s["regimes"]:
            s["regimes"][regime] = {"trades": 0, "wins": 0}
        s["regimes"][regime]["trades"] += 1
        if won:
            s["regimes"][regime]["wins"] += 1

        # Streak tracking
        if won:
            self.consecutive_wins += 1
            self.consecutive_losses = 0
            trigger = "TRADE_WIN"
        else:
            self.consecutive_losses += 1
            self.consecutive_wins = 0
            trigger = "TRADE_LOSS"

        # Check for streak-based trigger
        if self.consecutive_losses >= 2:
            trigger = "STREAK_LOSS"
        elif self.consecutive_wins >= 3:
            trigger = "STREAK_WIN"

        # Run micro-optimization
        event = self._micro_optimize(trade_num, trigger)
        self.optimization_events.append(event)

        # Every FULL_BACKTEST_INTERVAL trades, schedule a full backtest flag
        if trade_num % self.FULL_BACKTEST_INTERVAL == 0:
            event.trigger += " + FULL_BACKTEST_DUE"

        return event

    # ── Micro-Optimization (fast, no I/O) ─────────────────────────────────

    def _micro_optimize(self, trade_num: int, trigger: str) -> MicroOptimizationEvent:
        """
        Fast parameter adjustment based purely on live trade outcomes.
        Blended with historical backtest if available.
        Runs in < 10ms.
        """
        import app.core.strategy_engine as se_module

        changes: List[str] = []
        total_live = len(self.live_trades)

        if total_live < self.MIN_LIVE_TRADES_FOR_SIGNAL:
            return MicroOptimizationEvent(
                trade_number=trade_num, timestamp=datetime.datetime.now(),
                trigger=trigger, changes=["⏳ Collecting data (need 2+ trades)"],
                new_quality_score=self.current_quality_score,
                new_confluence=se_module.MULTI_TF_CONFIG["gates"]["min_confluence_strategies"],
                active_strategies=[
                    n for n, a in self.strategy_engine.active_strategies.items() if a
                ],
            )

        # ── Compute live performance metrics ────────────────────────────────
        recent = self.live_trades[-min(10, total_live):]  # last 10 trades
        live_wr   = sum(1 for t in recent if t.won) / len(recent) * 100
        live_pnl  = sum(t.pnl_inr for t in recent)
        win_pnls  = [t.pnl_pct for t in recent if t.won]
        loss_pnls = [abs(t.pnl_pct) for t in recent if not t.won]
        avg_win   = statistics.mean(win_pnls)  if win_pnls  else 0
        avg_loss  = statistics.mean(loss_pnls) if loss_pnls else 0
        pf_live   = (avg_win / avg_loss) if avg_loss else (2.0 if avg_win > 0 else 0.5)

        # ── Blend with historical if available ──────────────────────────────
        if self.historical_report:
            kept = [
                p for p in self.historical_report.strategy_profiles
                if p.recommendation != "DISABLE"
            ]
            hist_wr = statistics.mean(p.avg_win_rate for p in kept) if kept else 50.0
            blended_wr = live_wr * self.LIVE_WEIGHT + hist_wr * self.HIST_WEIGHT
        else:
            blended_wr = live_wr

        # ── Quality Score ───────────────────────────────────────────────────
        new_quality = min(100.0, max(0.0,
            blended_wr * 0.50 +
            min(pf_live, 3.0) / 3.0 * 30 +
            (10.0 if live_pnl >= 0 else 0.0) +
            (10.0 if self.consecutive_losses == 0 else max(0, 10 - self.consecutive_losses * 3))
        ))
        self.current_quality_score = round(new_quality, 1)

        # ── Confluence Adjustment ───────────────────────────────────────────
        old_confluence = se_module.MULTI_TF_CONFIG["gates"]["min_confluence_strategies"]
        if blended_wr >= 60 and pf_live >= 1.5:
            new_confluence = max(2, old_confluence - 1)   # loosen — allow more trades
            reason = f"High blended WR={blended_wr:.0f}%, PF={pf_live:.2f} → loosen confluence"
        elif blended_wr < 40 or self.consecutive_losses >= 2:
            new_confluence = min(5, old_confluence + 1)   # tighten — be selective
            reason = f"Low WR={blended_wr:.0f}% / {self.consecutive_losses} losses → tighten confluence"
        else:
            new_confluence = old_confluence
            reason = None

        if new_confluence != old_confluence:
            se_module.MULTI_TF_CONFIG["gates"]["min_confluence_strategies"] = new_confluence
            changes.append(f"🔄 min_confluence: {old_confluence} → {new_confluence} ({reason})")

        # ── Capital Per Trade Adjustment ────────────────────────────────────
        old_capital = self.risk_engine.config.max_capital_per_trade
        if blended_wr >= 65 and pf_live >= 1.8 and self.consecutive_losses == 0:
            new_capital = min(5000.0, old_capital * 1.10)   # scale up 10%
            new_capital = round(new_capital / 500) * 500    # round to nearest 500
            reason_c = f"Strong performance (WR={blended_wr:.0f}%) → scale up"
        elif blended_wr < 40 or self.consecutive_losses >= 3:
            new_capital = max(1500.0, old_capital * 0.80)   # scale down 20%
            new_capital = round(new_capital / 500) * 500
            reason_c = f"Weak performance (losses={self.consecutive_losses}) → scale down"
        else:
            new_capital = old_capital
            reason_c = None

        if new_capital != old_capital:
            self.risk_engine.config.max_capital_per_trade = new_capital
            changes.append(f"🔄 capital/trade: ₹{old_capital:.0f} → ₹{new_capital:.0f} ({reason_c})")

        # ── Strategy Enable/Disable Adjustment ─────────────────────────────
        for strat_name, stats in self.live_stats.items():
            if stats["trades"] < 3:
                continue   # not enough data
            live_strat_wr = stats["wins"] / stats["trades"] * 100
            is_active = self.strategy_engine.active_strategies.get(strat_name, True)

            if live_strat_wr < 30 and stats["trades"] >= 3 and is_active:
                self.strategy_engine.active_strategies[strat_name] = False
                changes.append(f"🔴 Disabled {strat_name} (live WR={live_strat_wr:.0f}% over {stats['trades']} trades)")
            elif live_strat_wr > 55 and not is_active:
                self.strategy_engine.active_strategies[strat_name] = True
                changes.append(f"🟢 Re-enabled {strat_name} (live WR recovered to {live_strat_wr:.0f}%)")

        # ── Trailing Stop Adjustment ────────────────────────────────────────
        if avg_win > 0:
            old_trailing = self.risk_engine.config.trailing_stop_activation_percent
            new_trailing = round(max(1.0, min(5.0, avg_win * 0.5)), 1)
            if abs(new_trailing - old_trailing) >= 0.5:
                self.risk_engine.config.trailing_stop_activation_percent = new_trailing
                changes.append(f"🔄 trailing_stop: {old_trailing}% → {new_trailing}% (avg win={avg_win:.1f}%)")

        if not changes:
            changes.append("✅ Parameters optimal — no adjustment needed")

        return MicroOptimizationEvent(
            trade_number=trade_num,
            timestamp=datetime.datetime.now(),
            trigger=trigger,
            changes=changes,
            new_quality_score=self.current_quality_score,
            new_confluence=se_module.MULTI_TF_CONFIG["gates"]["min_confluence_strategies"],
            active_strategies=[
                n for n, a in self.strategy_engine.active_strategies.items() if a
            ],
        )

    # ── Full Backtest Trigger ──────────────────────────────────────────────

    def needs_full_backtest(self) -> bool:
        """Returns True if it's time to run a full 3-year backtest."""
        n = len(self.live_trades)
        if n == 0:
            return True  # always run at start
        if self.current_quality_score < self.QUALITY_DROP_THRESHOLD:
            return True  # quality emergency
        if n % self.FULL_BACKTEST_INTERVAL == 0:
            return True  # periodic refresh
        return False

    def run_full_reoptimize(
        self,
        symbols: List[str],
        period: str = "3y",
        progress_callback=None,
    ) -> OptimizationReport:
        """
        Runs a full StrategyOptimizer pass and caches the result.
        Called periodically, not on every trade.
        """
        optimizer = StrategyOptimizer(self.strategy_engine, self.risk_engine)
        report = optimizer.optimize(symbols, period, progress_callback)
        self.historical_report = report
        return report

    # ── Summary for Dashboard ──────────────────────────────────────────────

    def get_live_summary(self) -> dict:
        """Returns a dict of live stats for dashboard display."""
        total = len(self.live_trades)
        wins  = sum(1 for t in self.live_trades if t.won)
        return {
            "total_trades":        total,
            "wins":                wins,
            "losses":              total - wins,
            "live_win_rate":       round(wins / total * 100, 1) if total else 0,
            "total_pnl_inr":       round(sum(t.pnl_inr for t in self.live_trades), 2),
            "consecutive_losses":  self.consecutive_losses,
            "consecutive_wins":    self.consecutive_wins,
            "quality_score":       self.current_quality_score,
            "optimization_events": len(self.optimization_events),
            "active_strategies":   [
                n for n, a in self.strategy_engine.active_strategies.items() if a
            ],
        }

    # ── PRE-TRADE OPTIMIZATION (called by Agent 1 for every scanned symbol) ─

    def pre_trade_optimize(
        self,
        symbol: str,
        period: str = "3y",
    ) -> dict:
        """
        Runs full 3-year backtesting for ONE symbol across ALL strategies.
        Derives optimal trade parameters and applies guardrail changes.
        """
        # Session-based quarantine for poor quality symbols
        if not hasattr(self, 'failed_bt_blacklist'):
            self.failed_bt_blacklist: Dict[str, str] = {}
            
        if symbol in self.failed_bt_blacklist:
            return {
                "symbol": symbol, "status": "QUARANTINED",
                "trade_verdict": "SKIP",
                "skip_reason": f"QUARANTINED: {self.failed_bt_blacklist[symbol]}",
                "best_strategy": "None", "win_rate": 0, "sharpe": 0,
                "profit_factor": 0, "max_drawdown": 0,
                "optimal_stop_pct": 5.0, "optimal_target_pct": 8.0,
                "optimal_capital": 0, "regime_verdict": "UNKNOWN",
                "guard_changes": [], "backtest_summary": ["🚫 Blacklisted for session due to poor 3yr history"],
                "all_strategy_ranks": [],
            }

        from app.core.backtester import run_real_backtest
        import app.core.strategy_engine as se_module

        guard_changes: List[str] = []
        strategy_ranks = []
        all_results: Dict[str, RealBacktestResult] = {}


        # ── Run all strategies for this symbol ─────────────────────────────
        for strat in self.strategy_engine.strategies:
            r = run_real_backtest(strat, symbol, period)
            all_results[strat.name] = r
            if not r.error and r.total_trades > 0:
                strategy_ranks.append({
                    "name":          strat.name,
                    "sharpe":        r.sharpe_ratio,
                    "win_rate":      r.win_rate,
                    "profit_factor": min(r.profit_factor, 10.0),
                    "max_drawdown":  r.max_drawdown_pct,
                    "avg_win_pct":   r.avg_win_pct,
                    "avg_loss_pct":  abs(r.avg_loss_pct),
                    "total_trades":  r.total_trades,
                })

        if not strategy_ranks:
            return {
                "symbol": symbol, "status": "NO_DATA",
                "trade_verdict": "SKIP",
                "skip_reason": "No historical data available for this symbol.",
                "best_strategy": "Ensemble", "win_rate": 0, "sharpe": 0,
                "profit_factor": 0, "max_drawdown": 0,
                "optimal_stop_pct": 5.0, "optimal_target_pct": 8.0,
                "optimal_capital": 2000.0, "regime_verdict": "UNKNOWN",
                "guard_changes": [], "backtest_summary": [], "all_strategy_ranks": [],
            }

        # ── Rank strategies: composite score (Sharpe 50% + WR 30% + PF 20%) ─
        for s in strategy_ranks:
            s["score"] = (
                min(s["sharpe"], 3.0) / 3.0 * 50 +
                s["win_rate"] / 100 * 30 +
                min(s["profit_factor"], 3.0) / 3.0 * 20
            )
        strategy_ranks.sort(key=lambda x: x["score"], reverse=True)
        best = strategy_ranks[0]

        # ── Derive optimal trade parameters from best strategy's backtest ───
        # Stop loss: 1.5× average losing trade, bounded [2%, 8%]
        optimal_stop_pct   = round(min(8.0, max(2.0, best["avg_loss_pct"] * 1.5)), 2)
        # Target: 0.8× average winning trade, bounded [3%, 15%]
        optimal_target_pct = round(min(15.0, max(3.0, best["avg_win_pct"] * 0.80)), 2)

        # Capital: scale with profit factor
        pf = best["profit_factor"]
        if pf >= 1.8 and best["win_rate"] >= 55:
            optimal_capital = 4000.0
        elif pf >= 1.3:
            optimal_capital = 3000.0
        elif pf >= 1.0:
            optimal_capital = 2000.0
        else:
            optimal_capital = 1500.0

        # ── Best regime for this symbol ─────────────────────────────────────
        best_result = all_results.get(best["name"])
        regime_verdict = "UNKNOWN"
        if best_result and best_result.regime_breakdown:
            regime_verdict = max(
                best_result.regime_breakdown,
                key=lambda r: best_result.regime_breakdown[r].get("pnl_inr", 0)
            )

        # ── Apply guardrail changes specific to this symbol ─────────────────
        old_confluence = se_module.MULTI_TF_CONFIG["gates"]["min_confluence_strategies"]

        # If best strategy Sharpe < 0.1, this is a risky symbol — tighten
        if best["sharpe"] < 0.10:
            new_conf = min(5, old_confluence + 1)
            if new_conf != old_confluence:
                se_module.MULTI_TF_CONFIG["gates"]["min_confluence_strategies"] = new_conf
                guard_changes.append(
                    f"🔄 min_confluence {old_confluence}→{new_conf} "
                    f"(risky symbol, best Sharpe={best['sharpe']:.2f})"
                )
        elif best["sharpe"] >= 0.5 and best["win_rate"] >= 55:
            new_conf = max(2, old_confluence - 1)
            if new_conf != old_confluence:
                se_module.MULTI_TF_CONFIG["gates"]["min_confluence_strategies"] = new_conf
                guard_changes.append(
                    f"🔄 min_confluence {old_confluence}→{new_conf} "
                    f"(high-confidence symbol, Sharpe={best['sharpe']:.2f})"
                )

        # Apply capital recommendation
        old_cap = self.risk_engine.config.max_capital_per_trade
        if optimal_capital != old_cap:
            self.risk_engine.config.max_capital_per_trade = optimal_capital
            guard_changes.append(
                f"🔄 capital/trade ₹{old_cap:.0f}→₹{optimal_capital:.0f} "
                f"(PF={pf:.2f}, WR={best['win_rate']:.1f}%)"
            )

        # ── Trade verdict (The "Backtest Quality Floor") ─────────────────────
        # We enforce a strict floor to avoid "gambling" on symbols with no edge.
        # SKIP if:
        # 1. Best strategy has negative expectancy (PF < 1.0)
        # 2. Win rate is too low for the derived risk/reward (< 35%)
        # 3. Sharpe is essentially zero or negative (no risk-adjusted return)
        
        pf_floor     = 1.05  # Need at least 5% edge over losses
        wr_floor     = 35.0
        sharpe_floor = 0.05
        
        if best["profit_factor"] < pf_floor:
            verdict = "SKIP"
            skip_reason = f"Poor Profit Factor ({best['profit_factor']:.2f} < {pf_floor}). No historical edge."
        elif best["win_rate"] < wr_floor:
            verdict = "SKIP"
            skip_reason = f"Low Win Rate ({best['win_rate']:.1f}% < {wr_floor}%). High probability of consecutive losses."
        elif best["sharpe"] < sharpe_floor:
            verdict = "SKIP"
            skip_reason = f"Low Sharpe Ratio ({best['sharpe']:.2f} < {sharpe_floor}). Poor risk-adjusted returns."
        else:
            verdict = "PROCEED"
            skip_reason = ""

        # If we skipped due to quality floor, add to session blacklist
        if verdict == "SKIP":
             self.failed_bt_blacklist[symbol] = skip_reason

        # ── Compact summary per strategy ─────────────────────────────────────
        backtest_summary = [
            f"{'🟢' if s['score'] >= 40 else '🟡' if s['score'] >= 20 else '🔴'} "
            f"{s['name']}: WR={s['win_rate']:.0f}% | Sharpe={s['sharpe']:.2f} | "
            f"PF={s['profit_factor']:.2f} | DD={s['max_drawdown']:.1f}%"
            for s in strategy_ranks
        ]

        # Cache this for reference in the live optimization log
        if "pre_trade_cache" not in vars(self):
            self.pre_trade_cache: Dict[str, dict] = {}
        self.pre_trade_cache[symbol] = {
            "best_strategy":    best["name"],
            "win_rate":         best["win_rate"],
            "sharpe":           best["sharpe"],
            "optimal_stop_pct": optimal_stop_pct,
            "optimal_target_pct": optimal_target_pct,
            "guard_changes":    guard_changes,
        }

        return {
            "symbol":             symbol,
            "status":             "OK",
            "trade_verdict":      verdict,
            "skip_reason":        skip_reason,
            "best_strategy":      best["name"],
            "all_strategy_ranks": strategy_ranks,
            "win_rate":           best["win_rate"],
            "profit_factor":      best["profit_factor"],
            "sharpe":             best["sharpe"],
            "max_drawdown":       best["max_drawdown"],
            "optimal_stop_pct":   optimal_stop_pct,
            "optimal_target_pct": optimal_target_pct,
            "optimal_capital":    optimal_capital,
            "regime_verdict":     regime_verdict,
            "guard_changes":      guard_changes,
            "backtest_summary":   backtest_summary,
            "all_strategy_ranks": strategy_ranks,
        }

