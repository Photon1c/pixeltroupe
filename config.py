"""Runtime configuration for PixelTroupe Lightning."""

from __future__ import annotations

import os


GRID_WIDTH = int(os.getenv("PIXELTROUPE_GRID_WIDTH", "24"))
GRID_HEIGHT = int(os.getenv("PIXELTROUPE_GRID_HEIGHT", "16"))
DEFAULT_AGENT_COUNT = int(os.getenv("PIXELTROUPE_AGENT_COUNT", "6"))
TICK_INTERVAL_SECONDS = float(os.getenv("PIXELTROUPE_TICK_SECONDS", "0.8"))
MAX_CHAT_LINES = int(os.getenv("PIXELTROUPE_MAX_CHAT_LINES", "64"))
