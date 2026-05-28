"""Streamlit Cloud entry — loads the 12-agent Zerodha intraday dashboard."""
import sys
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
    import ui.dashboard  # noqa: F401 — set_page_config + full UI live here
except Exception as e:
    st.error("Dashboard failed to load. Check Streamlit Cloud logs.")
    st.exception(e)
    st.stop()
