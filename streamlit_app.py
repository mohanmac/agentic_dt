"""Streamlit Cloud entry — temporary smoke test.

If you see "Hello World", Cloud UI works; restore full dashboard import below.
"""
import streamlit as st

st.set_page_config(page_title="Cloud smoke test", layout="wide")
st.title("Hello World")
st.success("If you see this, Streamlit Cloud UI is working.")
st.caption("Deploy OK — next step: restore full dashboard in streamlit_app.py (see streamlit_app_full.py).")
