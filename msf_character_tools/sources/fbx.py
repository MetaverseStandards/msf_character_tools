# SPDX-License-Identifier: MIT
"""FBX source adapter on ufbx 0.23.1, compiled into the C++ core (core/src/fbx.cpp).

ufbx loads the file from memory already in metres and right-handed +Y up,
applies geometric transforms to the points, compensates inherit modes and
moves pivots into the node matrices (adding helper nodes where it must).
Static and animated node TRS both come from ufbx's node-to-parent matrices.
"""
from __future__ import annotations

from .. import _native
from ..report import Diagnostic
from . import Generated, SourceParseError

_core = _native.built
UFBX_VERSION = _core.UFBX_VERSION


class FbxAdapter:
    name = "msf-ufbx"
    version = "1"
    formats = ("fbx",)

    def reader(self):
        return "ufbx " + UFBX_VERSION

    def convert(self, data, fmt, resolver, limits, options):
        try:
            glb, node_paths, target_keys, losses = _core._fbx_convert(
                data, options["influences"] == "top4", options.get("animation"), options.get("sample_rate"),
                limits.max_reader_memory, limits.max_animation_values, f"{self.name} {self.version}")
        except _core.FbxParseError as exc:
            raise SourceParseError(str(exc)) from None
        return Generated(glb=glb, node_paths=tuple(node_paths), target_keys=tuple(tuple(k) for k in target_keys),
                         dependencies=(), losses=tuple(Diagnostic(*d) for d in losses))


ADAPTER = FbxAdapter()
