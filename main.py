#!/usr/bin/env python3
"""yt-dlp GUI entry point.

    python main.py [URL ...]
"""

from __future__ import annotations

import sys

from app.application import main

if __name__ == '__main__':
    sys.exit(main())
