import sys
import os
from pathlib import Path

# Add the current directory to the system path to allow importing modules
sys.path.append(str(Path(__file__).parent))

# Import and run the dashboard
import ui.dashboard_v3
