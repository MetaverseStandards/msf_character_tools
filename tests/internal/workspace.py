# SPDX-License-Identifier: MIT
"""Inputs that live outside the repository, named by environment variables (see docs/testing.md)."""
import os
from pathlib import Path


def rcef_root():
    """The RCEF checkout for the gate tier: MSF_RCEF_ROOT, or $MSF/RCEF in a local workspace, or None."""
    if os.environ.get('MSF_RCEF_ROOT'):
        return Path(os.environ['MSF_RCEF_ROOT'])
    return Path(os.environ['MSF']) / 'RCEF' if os.environ.get('MSF') else None
