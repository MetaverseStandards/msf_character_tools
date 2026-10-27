# SPDX-License-Identifier: MIT
"""ufbx 0.23.1 (MIT option) behind the msf-tools C shim; see msf_ufbx_shim.h for the API."""
from ._native import ffi, lib  # noqa: F401

_packed = lib.msf_fbx_ufbx_version()
UFBX_VERSION = f"{_packed // 1000000}.{_packed // 1000 % 1000}.{_packed % 1000}"
SHIM_ABI = lib.msf_fbx_shim_abi()
