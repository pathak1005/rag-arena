"""
Ashish Pathak – Knowledge Architect Portfolio.
One-page site with embedded GraphRAG demo.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

# Import the homepage
from ui.homepage import *

# That's it. Homepage is now the entire app.
