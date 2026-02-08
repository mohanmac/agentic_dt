"""
Quick validation script to test imports and basic functionality.
"""
import sys
from pathlib import Path

# Add app to path
sys.path.insert(0, str(Path(__file__).parent))

print("=" * 80)
print("DayTradingPaperBot - Import Validation")
print("=" * 80)
print()

# Test imports
print("Testing imports...")
errors = []

try:
    from app.core import config
    print("[OK] app.core.config")
except Exception as e:
    print(f"[FAIL] app.core.config: {e}")
    errors.append(str(e))

try:
    from app.core import schemas
    print("[OK] app.core.schemas")
except Exception as e:
    print(f"[FAIL] app.core.schemas: {e}")
    errors.append(str(e))

try:
    from app.core import storage
    print("[OK] app.core.storage")
except Exception as e:
    print(f"[FAIL] app.core.storage: {e}")
    errors.append(str(e))

try:
    from app.core import utils
    print("[OK] app.core.utils")
except Exception as e:
    print(f"[FAIL] app.core.utils: {e}")
    errors.append(str(e))

try:
    from app.core import zerodha_auth
    print("[OK] app.core.zerodha_auth")
except Exception as e:
    print(f"[FAIL] app.core.zerodha_auth: {e}")
    errors.append(str(e))

try:
    from app.core import market_data
    print("[OK] app.core.market_data")
except Exception as e:
    print(f"[FAIL] app.core.market_data: {e}")
    errors.append(str(e))

try:
    from app.core import ollama_client
    print("[OK] app.core.ollama_client")
except Exception as e:
    print(f"[FAIL] app.core.ollama_client: {e}")
    errors.append(str(e))

try:
    from app.agents import strategy_brain
    print("[OK] app.agents.strategy_brain")
except Exception as e:
    print(f"[FAIL] app.agents.strategy_brain: {e}")
    errors.append(str(e))

try:
    from app.agents import risk_policy
    print("[OK] app.agents.risk_policy")
except Exception as e:
    print(f"[FAIL] app.agents.risk_policy: {e}")
    errors.append(str(e))

try:
    from app.agents import execution_paper
    print("[OK] app.agents.execution_paper")
except Exception as e:
    print(f"[FAIL] app.agents.execution_paper: {e}")
    errors.append(str(e))

try:
    from app import main
    print("[OK] app.main (FastAPI)")
except Exception as e:
    print(f"[FAIL] app.main: {e}")
    errors.append(str(e))

print()
print("=" * 80)

if not errors:
    print("[SUCCESS] All imports successful!")
    print()
    print("Next steps:")
    print("1. Edit .env file with your Zerodha credentials (if needed)")
    print("2. Start Ollama: ollama serve")
    print("3. Pull model: ollama pull qwen2.5:7b")
    print("4. Run: python -m app validate")
else:
    print(f"[ERROR] {len(errors)} import error(s) found")
    print()
    print("Errors:")
    for err in errors:
        print(f"  - {err}")

print("=" * 80)
