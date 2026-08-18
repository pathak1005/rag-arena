"""
Ashish Pathak – Knowledge Architect Portfolio.
Dark theme + pink accents. Animated hero + tabbed playground.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

# Import the homepage v2
from ui.homepage_v2 import *

# That's it.
