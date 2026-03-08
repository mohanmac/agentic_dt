import streamlit as st
import sys
import os
from pathlib import Path

# Add the current directory to the system path to allow importing modules
sys.path.append(str(Path(__file__).parent))

# Simple device detection (very basic) 
# Usually, mobile users have narrower screen widths on initial load
# But for Streamlit, we can offer a choice or just keep V4 as the default for mobile deployment
# For now, let's keep it clean: 
# Point to V4 for mobile-optimized deployment on Streamlit Cloud.

import ui.dashboard_v4
