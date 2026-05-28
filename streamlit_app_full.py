"""Full dashboard entry — restore by copying into streamlit_app.py after smoke test passes."""
import sys
from pathlib import Path

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

sys.path.append(str(Path(__file__).parent))

import ui.dashboard  # noqa: F401  — 12-agent proactive Zerodha intraday system
