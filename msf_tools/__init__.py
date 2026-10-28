# SPDX-License-Identifier: MIT
"""MSF tools: six stable APIs, plus documented reference helpers."""
from .report import Result, Report, Diagnostic, Loss
from .authoring import validate_authoring, load_authoring, ValidatedAuthoring
from .pack import compile_pack, Pack, survey_csv, coverage
from .snapshot import (inspect_asset, annotate_asset, AssetSnapshot, Sidecar,
                       LocalResolver, decode_accessor, morph_binding)
from .mapping import (compile_mapping, evaluate_mapping, profile_snapshot,
                      CompiledMapping, EvaluatedValues)
from .geometry import (evaluate_geometry, sample_animation, export_geometry_golden,
                       reparent_local, GeometryValues)
from .common import canonical_json

__version__ = "0.4.0"
__all__ = ["validate_authoring", "compile_pack", "inspect_asset", "compile_mapping",
           "evaluate_mapping", "annotate_asset", "Result", "Report", "Diagnostic", "Loss",
           "load_authoring", "profile_snapshot", "canonical_json", "decode_accessor",
           "LocalResolver", "morph_binding", "evaluate_geometry", "sample_animation",
           "export_geometry_golden", "reparent_local", "survey_csv", "coverage", "Pack",
           "AssetSnapshot", "Sidecar", "ValidatedAuthoring", "CompiledMapping",
           "EvaluatedValues", "GeometryValues"]
