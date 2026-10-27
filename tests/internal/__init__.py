# SPDX-License-Identifier: MIT
"""Tests of private modules; run with `python -m unittest discover -s tests/internal -t tests`.

They share helpers and fixtures with the public suite, so tests/public goes on the path.
"""
import sys
from pathlib import Path

_PUBLIC = str(Path(__file__).resolve().parents[1] / 'public')
if _PUBLIC not in sys.path:
    sys.path.insert(0, _PUBLIC)
