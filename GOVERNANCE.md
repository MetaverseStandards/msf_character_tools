# Governance and releases

Original documentation: CC-BY-SA-4.0.

This is an initial reference implementation. Repository publication and release ownership must be explicit before an external release; no organization, adoption or stable binary ABI is promised. Shared schemas/operators/reports and geometry reference belong to the shared tooling review boundary. Domain repositories own reviewed signal definitions/calibration/evidence. Host adapters own actual host execution evidence. Native modules own numerical and lifetime checks.

Semantic, technical and fixture review are distinct gates. A change can pass API tests while retaining unresolved calibration or visual questions. Report quality (`exact|approximate`), disposition, coupling and evidence status remain independent. The word exact applies to the declared operation and assumptions only.

Release checklist:

- Confirm code MIT and original docs/data/fixtures CC-BY-SA-4.0; preserve inherited terms.
- Freeze independent schema/data/operator versions and compatibility examples.
- Reproduce pack/CSV/coverage/SHA256SUMS and installed-package tests on supported Python versions.
- Execute analytical and adversarial tests; record actual native/host versions and results separately.
- Audit public artifacts for machine/private paths, credentials, stale generated data and unlicensed claims.
- State unsupported capabilities, resource limits, performance measurements and remaining artist/semantic gates.
- Confirm publisher/release reviewer and approved source revision before publishing; avoid changes in consumers' inherited survey byte formats.

Additional formats, native packaging on three operating systems, bindings beyond the bounded kernel and production artist acceptance require separate scope/owner/effort decisions. Current local checks do not establish those release gates.
