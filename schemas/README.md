# Portable wire schemas

Original schemas and documentation: CC-BY-SA-4.0. The schemas use JSON Schema draft 2020-12:

- [authoring.schema.json](authoring.schema.json): the merged authoring document.
- [pack.schema.json](pack.schema.json): the deterministic validated pack. It is the same wire document.
- [report.schema.json](report.schema.json): reports, with one diagnostic `ref` each, losses and the report version.
- [sidecar.schema.json](sidecar.schema.json): versioned structural bindings of scalar morph weights, and hashes.
- [samples.schema.json](samples.schema.json): an array of sample frames, for input or evaluated output.
- [diagnostics.toml](diagnostics.toml): every diagnostic code, with its severity, its rename under strict losses, its meaning and the release that added it. This file is MIT, unlike the other files here; see [NOTICE](../NOTICE.md).

The [reference](../docs/reference.md) defines the Python dataclasses and the snapshot, compiled and helper outputs. These portable schemas describe JSON shapes. Validation at run time also checks more: finite binary64 values, unique IDs across fragments, referential integrity, the bounds of sparse binary data, domains, the count and order of coefficients, and graph cycles. Standard JSON has no literals for NaN or infinity. A third-party schema validator is optional and is not a runtime dependency.
