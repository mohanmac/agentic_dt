# TEMPORARY DIAGNOSTIC — minimal Streamlit script to verify cloud renders at all.
# Real entry point is `import ui.dashboard` (commented out below). Restore after testing.
import streamlit as st

st.set_page_config(page_title="Diag", layout="wide")
st.title("✅ Hello from Streamlit Cloud")
st.write("If you see this on https://proactive-agentic-dt.streamlit.app/, "
         "Streamlit Cloud works and the bug is in `ui/dashboard.py`.")
st.write("If this stays blank too, Streamlit Cloud itself is misbehaving for this deploy.")

import sys, platform
st.caption(f"Python {platform.python_version()} · streamlit {st.__version__} · running on {platform.system()}")

# Real app — re-enable after diagnostic:
# from pathlib import Path
# try:
#     import truststore; truststore.inject_into_ssl()
# except ImportError:
#     pass
# sys.path.append(str(Path(__file__).parent))
# import ui.dashboard  # noqa: F401
