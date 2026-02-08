"""
CLI entry point for DayTradingPaperBot.
"""
import sys
import argparse
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

from app.core.config import settings, validate_settings
from app.core.utils import logger


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="DayTradingPaperBot - Agentic Paper Trading System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Start auth server
  python -m app auth
  
  # Run paper trading
  python -m app run --paper
  
  # Run live trading (requires confirmation)
  python -m app run --live
  
  # Reset daily state
  python -m app reset
  
  # Launch dashboard
  python -m app dashboard
        """
    )
    
    parser.add_argument(
        "command",
        choices=["auth", "run", "reset", "dashboard", "validate"],
        help="Command to execute"
    )
    
    parser.add_argument(
        "--paper",
        action="store_true",
        help="Run in paper trading mode (default)"
    )
    
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run in live trading mode (DANGEROUS - requires confirmation)"
    )
    
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for auth server (default: 8000)"
    )
    
    args = parser.parse_args()
    
    # Validate settings
    print("\n" + "=" * 80)
    print("DayTradingPaperBot - Agentic Paper Trading System")
    print("=" * 80 + "\n")
    
    validate_settings()
    print()
    
    # Execute command
    if args.command == "auth":
        run_auth_server(args.port)
    
    elif args.command == "run":
        if args.live:
            run_live_trading()
        else:
            run_paper_trading()
    
    elif args.command == "reset":
        reset_daily_state()
    
    elif args.command == "dashboard":
        run_dashboard()
    
    elif args.command == "validate":
        validate_system()


def run_auth_server(port: int = 8000):
    """Run FastAPI auth server."""
    print(f"Starting authentication server on port {port}...")
    print(f"\nOnce started, visit: http://127.0.0.1:{port}/auth/login_url")
    print("to get the Zerodha login URL.\n")
    
    from app.main import run_auth_server
    run_auth_server(port=port)


def run_paper_trading():
    """Run paper trading mode."""
    print("Starting PAPER TRADING mode...")
    print("This is a simulation - no real money at risk.\n")
    
    from app.core.scheduler import run_paper_trading
    run_paper_trading()


def run_live_trading():
    """Run live trading mode."""
    if not settings.ENABLE_LIVE_TRADING:
        print("❌ ERROR: Live trading is disabled in configuration")
        print("To enable, set ENABLE_LIVE_TRADING=true in .env file")
        print("\n⚠️  WARNING: Live trading involves real money risk!")
        print("Please ensure you have thoroughly tested in paper mode first.\n")
        return
    
    print("⚠️" * 40)
    print("LIVE TRADING MODE")
    print("⚠️" * 40)
    print("\nThis will trade with REAL MONEY!")
    print("Ensure you have:")
    print("  1. Thoroughly tested in paper mode")
    print("  2. Reviewed all guardrails and risk limits")
    print("  3. Understood the strategies being used")
    print("  4. Sufficient capital in your trading account\n")
    
    from app.core.scheduler import run_live_trading
    run_live_trading()


def reset_daily_state():
    """Reset daily trading state."""
    print("Resetting daily state...")
    
    from app.agents.risk_policy import risk_policy
    risk_policy.reset_daily_state()
    
    print("✅ Daily state reset successfully")
    print(f"   - Daily capital: ₹{settings.DAILY_CAPITAL}")
    print(f"   - Max daily loss: ₹{settings.MAX_DAILY_LOSS}")
    print(f"   - Max trades: {settings.MAX_TRADES_PER_DAY}")
    print(f"   - SAFE_MODE: Disabled\n")


def run_dashboard():
    """Launch Streamlit dashboard."""
    import subprocess
    
    print("Launching Streamlit dashboard...")
    print("Dashboard will open in your browser.\n")
    
    dashboard_path = Path(__file__).parent / "ui" / "dashboard.py"
    
    subprocess.run([
        "streamlit", "run",
        str(dashboard_path),
        "--server.port", "8501",
        "--server.headless", "true"
    ])


def validate_system():
    """Validate system prerequisites."""
    print("Validating system prerequisites...\n")
    
    all_good = True
    
    # Check Zerodha auth
    print("1. Checking Zerodha authentication...")
    from app.core.zerodha_auth import zerodha_auth
    is_valid, profile = zerodha_auth.validate_token()
    
    if is_valid:
        print(f"   ✅ Authenticated as: {profile.get('user_name')}")
    else:
        print("   ❌ Not authenticated")
        print("      Run: python -m app auth")
        all_good = False
    
    # Check LLM
    print(f"\n2. Checking LLM connection ({settings.LLM_PROVIDER})...")
    from app.core.llm import llm_client
    
    if llm_client.check_health():
        print(f"   ✅ LLM connected: {settings.LLM_PROVIDER}")
    else:
        print("   ❌ LLM not available")
        if settings.LLM_PROVIDER == "ollama":
            print("      Ensure Ollama is running: ollama serve")
        elif settings.LLM_PROVIDER == "google":
            print("      Ensure GOOGLE_API_KEY is set in .env")
        all_good = False
    
    # Check database
    print("\n3. Checking database...")
    try:
        from app.core.storage import storage
        daily_state = storage.get_or_create_daily_state()
        print(f"   ✅ Database initialized: {settings.get_db_file()}")
    except Exception as e:
        print(f"   ❌ Database error: {e}")
        all_good = False
    
    # Check configuration
    print("\n4. Checking configuration...")
    if settings.KITE_API_KEY and settings.KITE_API_KEY != "your_api_key_here":
        print("   ✅ API key configured")
    else:
        print("   ❌ API key not configured")
        print("      Set KITE_API_KEY in .env file")
        all_good = False
    
    if settings.KITE_API_SECRET and settings.KITE_API_SECRET != "your_api_secret_here":
        print("   ✅ API secret configured")
    else:
        print("   ❌ API secret not configured")
        print("      Set KITE_API_SECRET in .env file")
        all_good = False
    
    # Summary
    print("\n" + "=" * 80)
    if all_good:
        print("✅ All systems operational!")
        print("\nYou can now:")
        print("  - Run paper trading: python -m app run --paper")
        print("  - Launch dashboard: python -m app dashboard")
    else:
        print("❌ Some issues found - please resolve them before trading")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
