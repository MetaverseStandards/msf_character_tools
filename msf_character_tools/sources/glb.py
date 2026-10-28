# SPDX-License-Identifier: MIT
"""Deterministic GLB writer shared by source adapters.

Each source point becomes exactly one glTF vertex and triangle indices refer to
points, because the reference evaluator reads POSITION only; splitting corners
for normals or texture coordinates would multiply vertex and morph work.
Written by the C++ core (core/src/glb_writer.cpp).
"""
from __future__ import annotations

from dataclasses import dataclass

from .. import _native

_core = _native.built


@dataclass(frozen=True)
class Mesh:
    """One primitive. `targets` holds one offset per point per morph target;
    `influences` holds one sequence of (joint, weight) pairs per point."""
    points: tuple
    triangles: tuple = ()
    targets: tuple = ()
    influences: tuple | None = None
    weights: tuple = ()


@dataclass(frozen=True)
class Node:
    name: str | None = None
    children: tuple = ()
    translation: tuple = (0.0, 0.0, 0.0)
    rotation: tuple = (0.0, 0.0, 0.0, 1.0)
    scale: tuple = (1.0, 1.0, 1.0)
    mesh: int | None = None
    skin: int | None = None
    weights: tuple | None = None


@dataclass(frozen=True)
class Skin:
    """`inverse_bind_matrices` are 16 floats each, column-major as in glTF."""
    joints: tuple
    inverse_bind_matrices: tuple
    skeleton: int | None = None


@dataclass(frozen=True)
class Channel:
    """One sampler and channel. `values` holds one row per time: 3 numbers for
    translation and scale, an xyzw quaternion for rotation, or one weight per
    morph target of the node's mesh for weights."""
    node: int
    path: str
    times: tuple
    values: tuple
    interpolation: str = "LINEAR"


@dataclass(frozen=True)
class Animation:
    channels: tuple
    name: str | None = None


def write_glb(nodes, meshes, skins=(), animations=(), *, generator):
    """Return GLB bytes for nodes, meshes and skins given in final glTF index order."""
    return _core._write_glb(nodes, meshes, skins, animations, generator)
