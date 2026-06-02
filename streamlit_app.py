"""Streamlit Cloud entry — loads the 12-agent Zerodha intraday dashboard.

Streamlit re-runs THIS entry script top-to-bottom on every interaction and for
every visitor. A plain ``import ui.dashboard`` executes the dashboard's body
(all the st.* rendering) only ONCE per process, so every rerun after the first
would paint a blank page. We therefore RELOAD the module on each run so the UI
re-renders every time — exactly like running ``streamlit run ui/dashboard.py``
directly, which is how local dev runs it (and why local always worked).
"""
import sys
import importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

# Inject Streamlit [secrets] into os.environ before config/settings import.
from app.core.env_bootstrap import apply_env_bootstrap

apply_env_bootstrap()

import streamlit as st

try:
    _mod = sys.modules.get("ui.dashboard")
    if _mod is None:
        import ui.dashboard  # first run: executes set_page_config + full UI
    else:
        importlib.reload(_mod)  # every rerun: re-execute so the UI re-renders
except Exception as e:
    st.error("Dashboard failed to load. Check Streamlit Cloud logs.")
    st.exception(e)
    st.stop()
