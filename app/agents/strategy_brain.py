"""
Agent 1: StrategyBrainAgent
Evaluates market conditions and generates trade intents with LLM-powered reasoning.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime

from app.core.schemas import (
    MarketSnapshot, TradeIntent, StrategyType, TradeSide,
    OrderType, StrategyScore, MarketRegime
)
from app.core.llm import llm_client
from app.core.utils import logger, log_event
from app.core.config import settings


class StrategyBrainAgent:
    """
    Strategy evaluation agent that analyzes market conditions and proposes trades.
    
    Evaluates 3 strategies in parallel:
    1. Momentum Breakout
    2. Mean Reversion
    3. Volatility Expansion
    """
    
    def __init__(self):
        self.min_confidence_threshold = 0.6
        self.strategy_evaluators = {
            StrategyType.MOMENTUM_BREAKOUT: self._evaluate_momentum_breakout,
            StrategyType.MEAN_REVERSION: self._evaluate_mean_reversion,
            StrategyType.VOLATILITY_EXPANSION: self._evaluate_volatility_expansion
        }
    
    def evaluate(self, snapshot: MarketSnapshot) -> Optional[TradeIntent]:
        """
        Evaluate all strategies and return best trade intent or NO_TRADE.
        
        Args:
            snapshot: Current market snapshot
        
        Returns:
            TradeIntent if opportunity found, None for NO_TRADE
        """
        logger.info(f"Evaluating strategies for {snapshot.symbol}")
        
        # Evaluate all strategies in parallel
        scores: List[StrategyScore] = []
        
        for strategy_type, evaluator in self.strategy_evaluators.items():
            score = evaluator(snapshot)
            scores.append(score)
            
            log_event("strategy_evaluated", {
                "strategy": strategy_type.value,
                "confidence": score.confidence,
                "symbol": snapshot.symbol
            })
        
        # Select best strategy
        best_score = max(scores, key=lambda s: s.confidence)
        
        logger.info(f"Strategy scores: {[(s.strategy.value, f'{s.confidence:.2f}') for s in scores]}")
        logger.info(f"Best strategy: {best_score.strategy.value} (confidence: {best_score.confidence:.2f})")
        
        # Check if confidence meets threshold
        if best_score.confidence < self.min_confidence_threshold:
            log_event("no_trade_recommendation", {
                "reason": "confidence_below_threshold",
                "best_confidence": best_score.confidence,
                "threshold": self.min_confidence_threshold,
                "symbol": snapshot.symbol
            })
            logger.info(f"NO_TRADE: Best confidence {best_score.confidence:.2f} below threshold {self.min_confidence_threshold}")
            return None
        
        # Generate trade intent from best strategy
        intent = self._generate_trade_intent(snapshot, best_score)
        
        log_event("trade_intent_generated", {
            "strategy": intent.strategy_id.value,
            "symbol": intent.symbol,
            "side": intent.side.value,
            "confidence": intent.confidence_score,
            "expected_risk": intent.expected_risk_rupees
        })
        
        return intent
    
    def _evaluate_momentum_breakout(self, snapshot: MarketSnapshot) -> StrategyScore:
        """
        Evaluate momentum breakout strategy.
        
        Setup:
        - Opening range breakout (first 15min high/low)
        - VWAP breakout with volume confirmation
        - Trending regime preferred
        """
        confidence = 0.0
        rationale_points = []
        metrics = {}
        
        ltp = snapshot.ltp
        vwap = snapshot.vwap
        
        # Check for opening range breakout
        if snapshot.opening_range_high and snapshot.opening_range_low:
            or_high = snapshot.opening_range_high
            or_low = snapshot.opening_range_low
            
            if ltp > or_high:
                confidence += 0.25
                rationale_points.append(f"Price broke above opening range high ({or_high:.2f})")
                metrics['breakout_type'] = 'or_high'
            elif ltp < or_low:
                confidence += 0.25
                rationale_points.append(f"Price broke below opening range low ({or_low:.2f})")
                metrics['breakout_type'] = 'or_low'
        
        # VWAP breakout
        vwap_deviation = (ltp - vwap) / vwap * 100
        if abs(vwap_deviation) > 0.5:  # More than 0.5% from VWAP
            confidence += 0.2
            rationale_points.append(f"Price {vwap_deviation:+.2f}% from VWAP")
            metrics['vwap_deviation_pct'] = vwap_deviation
        
        # Volume confirmation
        if snapshot.avg_volume_20d and snapshot.volume > snapshot.avg_volume_20d * 1.2:
            confidence += 0.2
            rationale_points.append("Above-average volume confirms breakout")
            metrics['volume_ratio'] = snapshot.volume / snapshot.avg_volume_20d
        
        # Regime check
        if snapshot.regime in [MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN]:
            confidence += 0.2
            rationale_points.append(f"Trending regime ({snapshot.regime.value})")
        else:
            confidence -= 0.1
            rationale_points.append(f"Non-trending regime ({snapshot.regime.value}) reduces confidence")
        
        # Liquidity check
        if snapshot.liquidity_score > 0.7:
            confidence += 0.15
            rationale_points.append("High liquidity")
        
        # Cap confidence at 1.0
        confidence = min(confidence, 1.0)
        
        rationale = "Momentum Breakout: " + "; ".join(rationale_points) if rationale_points else "No clear breakout setup"
        
        return StrategyScore(
            strategy=StrategyType.MOMENTUM_BREAKOUT,
            confidence=max(0.0, confidence),
            rationale=rationale,
            key_metrics=metrics
        )
    
    def _evaluate_mean_reversion(self, snapshot: MarketSnapshot) -> StrategyScore:
        """
        Evaluate mean reversion strategy.
        
        Setup:
        - Price deviation from VWAP > 1.5 std
        - Bollinger Band touch
        - Ranging/whipsaw regime preferred
        """
        confidence = 0.0
        rationale_points = []
        metrics = {}
        
        ltp = snapshot.ltp
        vwap = snapshot.vwap
        
        # VWAP deviation
        vwap_deviation = abs(ltp - vwap) / vwap * 100
        if vwap_deviation > 1.5:
            confidence += 0.3
            rationale_points.append(f"Price {vwap_deviation:.2f}% from VWAP (mean reversion opportunity)")
            metrics['vwap_deviation_pct'] = vwap_deviation
        
        # Bollinger Band touch
        if snapshot.bb_upper and snapshot.bb_lower:
            bb_upper = snapshot.bb_upper
            bb_lower = snapshot.bb_lower
            bb_middle = snapshot.bb_middle or vwap
            
            # Check if price is near bands
            upper_distance = abs(ltp - bb_upper) / ltp * 100
            lower_distance = abs(ltp - bb_lower) / ltp * 100
            
            if upper_distance < 0.5:  # Within 0.5% of upper band
                confidence += 0.3
                rationale_points.append(f"Price near upper Bollinger Band ({bb_upper:.2f})")
                metrics['bb_touch'] = 'upper'
            elif lower_distance < 0.5:  # Within 0.5% of lower band
                confidence += 0.3
                rationale_points.append(f"Price near lower Bollinger Band ({bb_lower:.2f})")
                metrics['bb_touch'] = 'lower'
        
        # Regime check (prefer ranging/whipsaw)
        if snapshot.regime in [MarketRegime.RANGING, MarketRegime.WHIPSAW]:
            confidence += 0.25
            rationale_points.append(f"Ranging market ({snapshot.regime.value}) favors mean reversion")
        else:
            confidence -= 0.15
            rationale_points.append(f"Trending market ({snapshot.regime.value}) reduces mean reversion edge")
        
        # Volatility check (prefer moderate volatility)
        if 30 < snapshot.volatility_percentile < 70:
            confidence += 0.15
            rationale_points.append("Moderate volatility suitable for mean reversion")
        
        # Cap confidence
        confidence = min(confidence, 1.0)
        
        rationale = "Mean Reversion: " + "; ".join(rationale_points) if rationale_points else "No mean reversion setup"
        
        return StrategyScore(
            strategy=StrategyType.MEAN_REVERSION,
            confidence=max(0.0, confidence),
            rationale=rationale,
            key_metrics=metrics
        )
    
    def _evaluate_volatility_expansion(self, snapshot: MarketSnapshot) -> StrategyScore:
        """
        Evaluate volatility expansion strategy.
        
        Setup:
        - BB width compression (< 20th percentile)
        - ATR compression followed by expansion
        - Breakout from consolidation
        """
        confidence = 0.0
        rationale_points = []
        metrics = {}
        
        ltp = snapshot.ltp
        
        # Bollinger Band width compression
        if snapshot.bb_width and snapshot.atr:
            bb_width_pct = snapshot.bb_width / ltp * 100
            
            if bb_width_pct < 2.0:  # Tight BB width
                confidence += 0.3
                rationale_points.append(f"Bollinger Bands compressed ({bb_width_pct:.2f}%)")
                metrics['bb_width_pct'] = bb_width_pct
        
        # Volatility percentile (prefer low volatility before expansion)
        if snapshot.volatility_percentile < 30:
            confidence += 0.25
            rationale_points.append(f"Low volatility ({snapshot.volatility_percentile:.0f}th percentile) - expansion likely")
        elif snapshot.volatility_percentile > 70:
            # Already high volatility - expansion may be starting
            confidence += 0.15
            rationale_points.append(f"Volatility expanding ({snapshot.volatility_percentile:.0f}th percentile)")
        
        # Check for breakout from consolidation
        if snapshot.bb_upper and snapshot.bb_lower:
            bb_range = snapshot.bb_upper - snapshot.bb_lower
            if ltp > snapshot.bb_upper or ltp < snapshot.bb_lower:
                confidence += 0.25
                rationale_points.append("Price breaking out of Bollinger Bands")
                metrics['breakout_direction'] = 'up' if ltp > snapshot.bb_upper else 'down'
        
        # Volume surge (expansion confirmation)
        if snapshot.avg_volume_20d and snapshot.volume > snapshot.avg_volume_20d * 1.5:
            confidence += 0.2
            rationale_points.append("Volume surge confirms expansion")
            metrics['volume_ratio'] = snapshot.volume / snapshot.avg_volume_20d
        
        # Cap confidence
        confidence = min(confidence, 1.0)
        
        rationale = "Volatility Expansion: " + "; ".join(rationale_points) if rationale_points else "No volatility expansion setup"
        
        return StrategyScore(
            strategy=StrategyType.VOLATILITY_EXPANSION,
            confidence=max(0.0, confidence),
            rationale=rationale,
            key_metrics=metrics
        )
    
    def _generate_trade_intent(self, snapshot: MarketSnapshot, score: StrategyScore) -> TradeIntent:
        """
        Generate trade intent from strategy score.
        
        Args:
            snapshot: Market snapshot
            score: Strategy score
        
        Returns:
            TradeIntent with all required fields
        """
        ltp = snapshot.ltp
        strategy = score.strategy
        
        # Determine trade direction and prices based on strategy
        if strategy == StrategyType.MOMENTUM_BREAKOUT:
            # Breakout direction based on VWAP
            if ltp > snapshot.vwap:
                side = TradeSide.BUY
                entry_price = None  # Market order
                stop_loss_price = snapshot.vwap * 0.995  # 0.5% below VWAP
                target_price = ltp * 1.015  # 1.5% target
            else:
                side = TradeSide.SELL
                entry_price = None
                stop_loss_price = snapshot.vwap * 1.005
                target_price = ltp * 0.985
        
        elif strategy == StrategyType.MEAN_REVERSION:
            # Revert to VWAP
            if ltp > snapshot.vwap:
                side = TradeSide.SELL  # Price above VWAP, expect reversion down
                entry_price = ltp  # Limit order at current price
                stop_loss_price = ltp * 1.01  # 1% stop
                target_price = snapshot.vwap  # Target VWAP
            else:
                side = TradeSide.BUY  # Price below VWAP, expect reversion up
                entry_price = ltp
                stop_loss_price = ltp * 0.99
                target_price = snapshot.vwap
        
        else:  # VOLATILITY_EXPANSION
            # Breakout direction
            if snapshot.bb_upper and ltp > snapshot.bb_upper:
                side = TradeSide.BUY
                entry_price = None  # Market order on expansion
                stop_loss_price = snapshot.bb_middle or (ltp * 0.99)
                target_price = ltp * 1.02  # 2% target
            elif snapshot.bb_lower and ltp < snapshot.bb_lower:
                side = TradeSide.SELL
                entry_price = None
                stop_loss_price = snapshot.bb_middle or (ltp * 1.01)
                target_price = ltp * 0.98
            else:
                # Default to buy on expansion
                side = TradeSide.BUY
                entry_price = None
                stop_loss_price = ltp * 0.99
                target_price = ltp * 1.02
        
        # Calculate quantity (default to 1 share, will be adjusted by RiskPolicyAgent)
        quantity = 1
        
        # Calculate expected risk
        expected_risk = abs(ltp - stop_loss_price) * quantity
        
        # Generate LLM rationale
        llm_rationale = self._generate_llm_rationale(snapshot, score, side, stop_loss_price, target_price)
        
        # Build invalidation conditions
        invalidation_conditions = self._build_invalidation_conditions(snapshot, strategy)
        
        # Create trade intent
        intent = TradeIntent(
            strategy_id=strategy,
            symbol=snapshot.symbol,
            side=side,
            entry_type=OrderType.MARKET if entry_price is None else OrderType.LIMIT,
            entry_price=entry_price,
            quantity=quantity,
            stop_loss_price=stop_loss_price,
            target_price=target_price,
            confidence_score=score.confidence,
            rationale=llm_rationale,
            expected_risk_rupees=expected_risk,
            invalidation_conditions=invalidation_conditions
        )
        
        return intent
    
    def _generate_llm_rationale(
        self,
        snapshot: MarketSnapshot,
        score: StrategyScore,
        side: TradeSide,
        stop_loss: float,
        target: float
    ) -> str:
        """
        Generate human-readable rationale using Ollama LLM.
        
        Args:
            snapshot: Market snapshot
            score: Strategy score
            side: Trade side
            stop_loss: Stop-loss price
            target: Target price
        
        Returns:
            LLM-generated rationale
        """
        system_prompt = """You are a professional day trader explaining your trade setup.
Be concise, specific, and focus on key risk/reward factors.
Limit response to 2-3 sentences."""
        
        prompt = f"""Explain this {score.strategy.value} trade setup:

Symbol: {snapshot.symbol}
Current Price: ₹{snapshot.ltp:.2f}
VWAP: ₹{snapshot.vwap:.2f}
Market Regime: {snapshot.regime.value}
Trend: {snapshot.trend_direction}

Trade: {side.value.upper()} at market
Stop-Loss: ₹{stop_loss:.2f}
Target: ₹{target:.2f}
Confidence: {score.confidence:.0%}

Strategy Analysis: {score.rationale}

Explain why this trade makes sense and what the key risks are."""
        
        try:
            llm_response = llm_client.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                temperature=0.7,
                max_tokens=200
            )
            
            # Combine rule-based rationale with LLM explanation
            full_rationale = f"{score.rationale}\n\nAnalysis: {llm_response}"
            return full_rationale
        
        except Exception as e:
            logger.warning(f"LLM rationale generation failed: {e}")
            return score.rationale
    
    def _build_invalidation_conditions(self, snapshot: MarketSnapshot, strategy: StrategyType) -> List[str]:
        """Build list of conditions that would invalidate the trade setup."""
        conditions = []
        
        if strategy == StrategyType.MOMENTUM_BREAKOUT:
            conditions.append(f"Price falls back below VWAP (₹{snapshot.vwap:.2f})")
            conditions.append("Volume drops significantly")
            conditions.append("Regime changes to ranging/whipsaw")
        
        elif strategy == StrategyType.MEAN_REVERSION:
            conditions.append("Price continues trending away from VWAP")
            conditions.append("Regime changes to strong trending")
            conditions.append("Volume surge indicates breakout, not reversion")
        
        else:  # VOLATILITY_EXPANSION
            conditions.append("Volatility contracts again (false breakout)")
            conditions.append("Price returns inside Bollinger Bands")
            conditions.append("Volume dries up")
        
        return conditions


# Global strategy brain agent instance
strategy_brain = StrategyBrainAgent()
