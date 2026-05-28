# deploy-marker: full-dashboard-2026-03-16 (not Hello World smoke test)
import sys
from pathlib import Path

# Use macOS / Windows system trust store so corporate MITM SSL proxies' CA certs
# (already installed in the OS keychain) are trusted. Must run before any HTTPS call.
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

sys.path.append(str(Path(__file__).parent))

import ui.dashboard  # noqa: F401  — 12-agent proactive Zerodha intraday system
