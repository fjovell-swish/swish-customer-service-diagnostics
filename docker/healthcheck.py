#!/usr/bin/env python
"""The image's HEALTHCHECK: fails (exit 1, with the error) unless /healthz answers on $PORT."""

import os
import urllib.request

TIMEOUT_SECONDS = 4

urllib.request.urlopen(
    f"http://127.0.0.1:{os.environ.get('PORT', '8000')}/healthz", timeout=TIMEOUT_SECONDS
)
