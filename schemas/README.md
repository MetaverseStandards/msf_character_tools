# Portable wire schemas

Original schemas and documentation: CC-BY-SA-4.0. JSON Schema draft 2020-12:

- [authoring.schema.json](authoring.schema.json): merged authoring document.
- [pack.schema.json](pack.schema.json): deterministic validated pack; same wire document.
- [report.schema.json](report.schema.json): singular diagnostic `ref`, losses and report version.
- [sidecar.schema.json](sidecar.schema.json): versioned structural scalar morph bindings and hashes.
- [samples.schema.json](samples.schema.json): input/evaluated sample frame array.

The [reference](../docs/reference.md) defines Python dataclasses and snapshot/compiled/helper outputs. These portable schemas describe JSON shapes; runtime validation additionally enforces finite binary64 values, unique IDs across fragments, referential integrity, sparse binary bounds, domains, ordered coefficient arity and graph cycles. Standard JSON has no NaN/infinity literals. A third-party schema validator is optional and is not a runtime dependency.
