# SPDX-License-Identifier: MIT
"""Independent position geometry and animation reference; no taxonomy dependency.

Evaluated in the C++ core (core/src/gltf_geometry.cpp, core/src/gltf_binary.cpp).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .common import freeze, thaw, number
from .snapshot import AssetSnapshot, SUPPORTED_REQUIRED_EXTENSIONS, MAX_TOTAL_ACCESSOR_COMPONENTS, _identity, _source_summary
from .math3d import matrix, multiply, inverse, column_major, affine, validate_trs
from .report import public, fail, Result, Report, Diagnostic
from .records import OwnedRecord, _admit

# Position components read and written per mesh node instance (the base POSITION
# plus every morph-target POSITION), summed over instances, plus one set of inverse
# bind matrices per skin used. Inspection caps declared accessor components at the
# same number, so an asset that evaluates each of those accessors once fits;
# instancing a mesh or sharing accessors multiplies the work.
MAX_EVALUATION_COMPONENTS = MAX_TOTAL_ACCESSOR_COMPONENTS


def vector(value, count, ref):
    if not isinstance(value, (tuple, list)) or len(value) != count or not all(number(x) for x in value):
        fail("E_TYPE", ref, f"Expected {count} finite numeric components.")


def _time(timestamp):
    if not number(timestamp) or timestamp < 0:
        fail("E_TIMESTAMP", "/timestamp", "Timestamp must be nonnegative finite seconds.")


def _asset(snapshot):
    if not isinstance(snapshot, AssetSnapshot) or snapshot.format == "profile":
        fail("E_SNAPSHOT", "/", "Expected an inspected glTF/GLB snapshot.")
    snapshot._check_integrity()
    unsupported = set(snapshot.document.get("extensionsRequired", ())) - SUPPORTED_REQUIRED_EXTENSIONS
    if unsupported:
        fail("E_REQUIRED_EXTENSION", "/extensionsRequired", "Requested evaluation has unsupported required behavior: " + ", ".join(sorted(unsupported)))


@public
def sample_animation(snapshot, animation_id, timestamp):
    _asset(snapshot)
    _time(timestamp)
    return snapshot._core.sample(animation_id, timestamp)


@dataclass(frozen=True)
class GeometryValues(OwnedRecord):
    _handle_views = ("instances",)
    timestamp: float
    instances: tuple
    _core: object = field(default=None, init=False, repr=False, compare=False)

    def _check_consistency(self):
        if self._core is None or not self._core.check_view(self.instances):
            fail("E_RECORD_INTEGRITY", "/", "Geometry view disagrees with its core positions.")

    def to_dict(self):
        self._check_integrity()
        return {"timestamp": self.timestamp, "instances": thaw(self.instances)}


@public
def evaluate_geometry(snapshot, *, timestamp=0.0, animation_id=None, morph_weights=None, node_transforms=None, attributes=("POSITION",)):
    _asset(snapshot)
    _time(timestamp)
    if tuple(attributes) != ("POSITION",):
        fail("E_GEOMETRY_CAPABILITY", "/attributes", "Reference evaluation supports positions only.")
    budget = MAX_EVALUATION_COMPONENTS if snapshot.source is None else snapshot._component_caps()[1]
    diagnostics, positions = snapshot._core.evaluate(timestamp, animation_id, morph_weights, node_transforms, budget)
    report = Report(tuple(Diagnostic(*d) for d in diagnostics))
    if positions is None:
        return Result(None, report)
    record = GeometryValues(float(timestamp), positions.view)
    object.__setattr__(record, "_core", positions)
    return Result(_admit(record), report)


@public
def export_geometry_golden(snapshot, **kwargs):
    result = evaluate_geometry(snapshot, **kwargs)
    if not result.ok:
        return result
    golden = {"schema_version": "1.0", "asset_sha256": _identity(snapshot),
              "precision": "binary64", "coordinates": "mesh_local", "units": "metres",
              "evaluation": result.value.to_dict()}
    if snapshot.source is not None:
        golden["source"] = _source_summary(snapshot)
    return freeze(golden)


@public
def reparent_local(child_world, new_parent_world):
    """Hierarchy probe only. Reject shear/singular TRS; no skin preservation claim."""
    vector(child_world, 16, "/child_world")
    vector(new_parent_world, 16, "/new_parent_world")
    child = affine(matrix(child_world), 1e-9, '/child_world')
    parent = affine(matrix(new_parent_world), 1e-9, '/new_parent_world')
    local = multiply(inverse(parent), child)
    validate_trs(local, ref='/reparent')
    return tuple(column_major(local))
