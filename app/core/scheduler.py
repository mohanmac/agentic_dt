"""
Scheduler and orchestrator for the trading loop.
Coordinates all 3 agents and manages the trading workflow.
"""
import time
from datetime import datetime, timedelta
from typing import Optional
import signal
import sys

from app.core.config import settings
from app.core.utils import logger, log_event, is_trading_hours, is_exit_only_time
from app.core.storage import storage
from app.core.market_data import market_data
from app.agents.strategy_brain import strategy_brain
from app.agents.risk_policy import risk_policy
from app.agents.execution_paper import execution_paper
from app.core.llm import llm_client


class TradingScheduler:
    """
    Main orchestrator for the trading system.
    
    Coordinates:
    1. Market data refresh
    2. Strategy evaluation (StrategyBrainAgent)
    3. Risk approval (RiskPolicyAgent)
    4. Execution (ExecutionPaperAgent)
    5. Position monitoring
    """
    
    def __init__(self, paper_mode: bool = True):
        self.paper_mode = paper_mode
        self.running = False
        self.loop_interval = 60  # 1 minute
        self.symbols = settings.get_trading_symbols()
        
        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.stop()
    
    def start(self):
        """Start the trading loop."""
        logger.info("=" * 80)
        logger.info(f"DayTradingPaperBot Starting - Mode: {'PAPER' if self.paper_mode else 'LIVE'}")
        logger.info("=" * 80)
        
        log_event("trading_loop_started", {
            "mode": "paper" if self.paper_mode else "live",
            "symbols": self.symbols,
            "loop_interval": self.loop_interval
        })
        
        # Validate prerequisites
        if not self._validate_prerequisites():
            logger.error("Prerequisites not met, cannot start trading loop")
            return
        
        self.running = True
        
        try:
            while self.running:
                self._run_trading_cycle()
                
                # Sleep until next cycle
                if self.running:
                    logger.debug(f"Sleeping for {self.loop_interval} seconds...")
                    time.sleep(self.loop_interval)
        
        except Exception as e:
            logger.error(f"Fatal error in trading loop: {e}", exc_info=True)
            log_event("trading_loop_error", {"error": str(e)}, level="ERROR")
        
        finally:
            self._cleanup()
    
    def stop(self):
        """Stop the trading loop."""
        logger.info("Stopping trading loop...")
        self.running = False
    
    def _validate_prerequisites(self) -> bool:
        """Validate that all prerequisites are met."""
        # Check Zerodha authentication
        from app.core.zerodha_auth import zerodha_auth
        is_valid, profile = zerodha_auth.validate_token()
        
        if not is_valid:
            logger.error("Zerodha authentication failed. Please run auth flow first.")
            logger.error("Run: python -m app auth")
            return False
        
        logger.info(f"✓ Authenticated as: {profile.get('user_name')}")
        
        # Check LLM
        from app.core.llm import llm_client
        if not llm_client.check_health():
            logger.warning("⚠ LLM health check failed - strategy reasoning may be limited")
            logger.warning(f"  Provider: {settings.LLM_PROVIDER}")
            if settings.LLM_PROVIDER == "ollama":
                logger.warning("  Please ensure Ollama is running: ollama serve")
            elif settings.LLM_PROVIDER == "google":
                logger.warning("  Please ensure GOOGLE_API_KEY is set")
        else:
            logger.info(f"✓ LLM connected: {settings.LLM_PROVIDER}")
        
        # Check trading mode
        if not self.paper_mode and settings.ENABLE_LIVE_TRADING:
            logger.warning("⚠" * 40)
            logger.warning("LIVE TRADING MODE ENABLED - REAL MONEY AT RISK!")
            logger.warning("⚠" * 40)
            
            # Require explicit confirmation
            response = input("Type 'YES I UNDERSTAND' to proceed with live trading: ")
            if response != "YES I UNDERSTAND":
                logger.error("Live trading not confirmed, exiting")
                return False
        
        logger.info(f"✓ Trading mode: {'PAPER' if self.paper_mode else 'LIVE'}")
        logger.info(f"✓ Symbols: {', '.join(self.symbols)}")
        
        return True
    
    def _run_trading_cycle(self):
        """Run one complete trading cycle."""
        cycle_start = datetime.now()
        
        logger.info(f"\n{'=' * 80}")
        logger.info(f"Trading Cycle: {cycle_start.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"{'=' * 80}")
        
        # Check if we're in trading hours
        in_trading_hours, reason = is_trading_hours()
        if not in_trading_hours:
            logger.info(f"Outside trading hours: {reason}")
            return
        
        # Check if we're in exit-only mode
        exit_only = is_exit_only_time()
        if exit_only:
            logger.info("Exit-only mode: No new trades, monitoring positions only")
        
        # Get daily state
        daily_state = storage.get_or_create_daily_state()
        
        logger.info(f"Daily State: Trades={daily_state.trades_count}/{daily_state.max_trades}, "
                   f"PnL=₹{daily_state.total_pnl:+.2f}, "
                   f"Budget=₹{daily_state.loss_budget_remaining:.2f}, "
                   f"SAFE_MODE={daily_state.safe_mode}")
        
        # Step 1: Monitor existing positions
        logger.info("\n[1/5] Monitoring positions...")
        exit_actions = execution_paper.monitor_positions()
        
        if exit_actions:
            for action in exit_actions:
                logger.info(f"  Position exited: {action['symbol']} ({action['reason']}) - PnL: ₹{action['realized_pnl']:+.2f}")
        else:
            logger.info("  No position exits")
        
        # If SAFE_MODE, flatten all positions and stop
        if daily_state.safe_mode:
            logger.warning("SAFE_MODE active - flattening all positions")
            execution_paper.flatten_all_positions("safe_mode")
            return
        
        # If exit-only mode, skip new trade generation
        if exit_only:
            logger.info("Exit-only mode - skipping trade generation")
            return
        
        # Step 2: Fetch market data for all symbols
        logger.info(f"\n[2/5] Fetching market data for {len(self.symbols)} symbols...")
        
        for symbol in self.symbols:
            try:
                # Build market snapshot
                snapshot = market_data.build_market_snapshot(symbol)
                
                # Save snapshot
                snapshot_id = storage.save_market_snapshot(snapshot)
                
                logger.info(f"  {symbol}: LTP=₹{snapshot.ltp:.2f}, "
                           f"Regime={snapshot.regime.value}, "
                           f"Trend={snapshot.trend_direction}, "
                           f"Vol={snapshot.volatility_percentile:.0f}%ile")
                
                # Step 3: Strategy evaluation
                logger.info(f"\n[3/5] Evaluating strategies for {symbol}...")
                
                intent = strategy_brain.evaluate(snapshot)
                
                if intent is None:
                    logger.info(f"  NO_TRADE recommendation for {symbol}")
                    continue
                
                # Link intent to snapshot
                intent.market_snapshot_id = snapshot_id
                
                # Save intent
                intent_id = storage.save_trade_intent(intent)
                
                logger.info(f"  Trade Intent: {intent.strategy_id.value} {intent.side.value} "
                           f"{intent.quantity} @ ₹{intent.entry_price or 'MARKET'}, "
                           f"SL=₹{intent.stop_loss_price:.2f}, "
                           f"Confidence={intent.confidence_score:.2%}")
                
                # Step 4: Risk approval
                logger.info(f"\n[4/5] Risk approval for {symbol}...")
                
                approval = risk_policy.approve(intent, intent_id)
                
                # Save approval
                storage.save_approval(approval)
                
                if not approval.approved:
                    logger.warning(f"  REJECTED: {approval.rejection_reason}")
                    storage.update_intent_status(intent_id, 'rejected')
                    continue
                
                logger.info(f"  APPROVED: Quantity={approval.adjusted_quantity or intent.quantity}")
                
                # Check HITL requirement
                if approval.hitl_required:
                    logger.info(f"  HITL REQUIRED: {approval.hitl_reason}")
                    logger.info(f"  Trade pending human approval in dashboard")
                    storage.update_intent_status(intent_id, 'pending_hitl')
                    
                    # Update daily state
                    daily_state.hitl_approvals_pending += 1
                    storage.save_daily_state(daily_state)
                    
                    continue
                
                # Step 5: Execution
                logger.info(f"\n[5/5] Executing trade for {symbol}...")
                
                order = execution_paper.execute(intent, approval)
                
                if order and order.status == OrderStatus.FILLED:
                    logger.info(f"  ORDER FILLED: {order.side.value} {order.quantity} @ ₹{order.fill_price:.2f}, "
                               f"Slippage=₹{order.slippage:.2f}, Brokerage=₹{order.brokerage:.2f}")
                    storage.update_intent_status(intent_id, 'executed')
                else:
                    logger.warning(f"  Order execution failed or pending")
                    storage.update_intent_status(intent_id, 'execution_failed')
            
            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}", exc_info=True)
                continue
        
        # Log cycle completion
        cycle_duration = (datetime.now() - cycle_start).total_seconds()
        logger.info(f"\nCycle completed in {cycle_duration:.2f}s")
        logger.info(f"{'=' * 80}\n")
    
    def _cleanup(self):
        """Cleanup before shutdown."""
        logger.info("Performing cleanup...")
        
        # Flatten positions if end of day
        if is_exit_only_time():
            logger.info("End of day - flattening all positions")
            execution_paper.flatten_all_positions("end_of_day")
        
        log_event("trading_loop_stopped")
        logger.info("Trading loop stopped")


def run_paper_trading():
    """Run paper trading mode."""
    scheduler = TradingScheduler(paper_mode=True)
    scheduler.start()


def run_live_trading():
    """Run live trading mode (requires confirmation)."""
    if not settings.ENABLE_LIVE_TRADING:
        logger.error("Live trading is disabled in configuration")
        logger.error("Set ENABLE_LIVE_TRADING=true in .env to enable")
        return
    
    scheduler = TradingScheduler(paper_mode=False)
    scheduler.start()


if __name__ == "__main__":
    run_paper_trading()
