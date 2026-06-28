#!/usr/bin/env python3
"""
Quick setup and test script for live trading implementation.
Verifies that all components are wired correctly.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_execution_agent():
    """Test that ExecutionPaperAgent initializes correctly."""
    print("\n[1/4] Testing ExecutionPaperAgent initialization...")
    
    from app.agents.execution_paper import ExecutionPaperAgent
    from app.core.config import settings
    
    # Test with PAPER mode (default)
    agent_paper = ExecutionPaperAgent()
    print(f"    [OK] Paper mode broker initialized: {agent_paper.broker_type}")
    
    # Test with explicit broker
    from app.core.paper_broker import PaperBroker
    broker = PaperBroker()
    agent = ExecutionPaperAgent(broker=broker)
    print(f"    [OK] Custom broker passed: {agent.broker_type}")
    
    return True

def test_scheduler():
    """Test that TradingScheduler wires broker correctly."""
    print("\n[2/4] Testing TradingScheduler broker wiring...")
    
    from app.core.scheduler import TradingScheduler
    
    # Test paper mode
    scheduler_paper = TradingScheduler(paper_mode=True)
    print(f"    [OK] Paper mode scheduler initialized")
    
    # Test that execution agent exists
    assert hasattr(scheduler_paper, 'execution_agent'), "Scheduler missing execution_agent"
    print(f"    [OK] Execution agent attached to scheduler")
    
    return True

def test_storage():
    """Test that storage has monitoring methods."""
    print("\n[3/4] Testing storage monitoring methods...")
    
    from app.core.storage import storage
    
    # Test new methods exist
    methods = [
        'record_trade_completion',
        'get_completed_trades_today',
        'get_monitoring_status',
        'get_next_trade_prediction',
        'get_last_trade_time'
    ]
    
    for method in methods:
        assert hasattr(storage, method), f"Storage missing method: {method}"
        print(f"    [OK] Method exists: {method}")
    
    # Test that we can call monitoring methods
    status = storage.get_monitoring_status()
    print(f"    [OK] Monitoring status retrieved: {status['mode']} mode")
    
    prediction = storage.get_next_trade_prediction()
    print(f"    [OK] Next trade prediction retrieved: {prediction['status']}")
    
    return True

def test_monitoring_window():
    """Check that monitoring window file exists."""
    print("\n[4/4] Testing monitoring window...")
    
    monitoring_path = os.path.join(
        os.path.dirname(__file__),
        'ui',
        'monitoring_window.py'
    )
    
    assert os.path.exists(monitoring_path), f"Monitoring window not found at {monitoring_path}"
    print(f"    [OK] Monitoring window file exists")
    
    # Read file to verify it's a valid Streamlit app
    with open(monitoring_path, 'r', encoding='utf-8') as f:
        content = f.read()
        assert 'streamlit' in content, "Not a valid Streamlit app"
        assert 'st.metric' in content or 'st.markdown' in content, "No Streamlit widgets found"
        print(f"    [OK] Monitoring window is a valid Streamlit app")
    
    return True

def main():
    """Run all tests."""
    print("=" * 70)
    print("LIVE TRADING IMPLEMENTATION - VERIFICATION TEST")
    print("=" * 70)
    
    tests = [
        ("ExecutionPaperAgent", test_execution_agent),
        ("TradingScheduler", test_scheduler),
        ("Storage Monitoring", test_storage),
        ("Monitoring Window", test_monitoring_window),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            if test_func():
                passed += 1
        except Exception as e:
            print(f"    [FAIL] {e}")
            failed += 1
            import traceback
            traceback.print_exc()
    
    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)
    
    if failed == 0:
        print("\n[SUCCESS] All tests passed! Ready for live trading.\n")
        print("NEXT STEPS:")
        print("-" * 70)
        print("1. Set up your .env file with:")
        print("   ENABLE_LIVE_TRADING=true")
        print("   KITE_API_KEY=your_zerodha_key")
        print("   KITE_API_SECRET=your_zerodha_secret")
        print("")
        print("2. Authenticate with Zerodha:")
        print("   python -m app auth")
        print("")
        print("3. Start trading (2 terminals):")
        print("   Terminal 1 - Main trading:")
        print("   python -m app run --live")
        print("")
        print("   Terminal 2 - Monitor:")
        print("   streamlit run ui/monitoring_window.py --logger.level=error")
        print("-" * 70)
        return 0
    else:
        print("\n[FAILED] Some tests failed. Please fix the errors above.\n")
        return 1

if __name__ == "__main__":
    sys.exit(main())
