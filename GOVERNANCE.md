# Governance and releases

Original documentation: CC-BY-SA-4.0.

This is an initial reference implementation. Ken Jakubzak and the Metaverse Standards Forum 3D Assets working group own repository publication and releases. The project promises no organization, no adoption and no stable binary ABI. These are the review boundaries:
- Shared tooling review owns the shared schemas, operators, reports and the geometry reference.
- Domain repositories own reviewed signal definitions, calibration and evidence.
- Host adapters own the evidence that comes from running on a real host.
- Native modules own the numeric and lifetime checks.

Semantic review, technical review and fixture review are separate gates. A change can pass the API tests while calibration or visual questions stay open. Report quality (`exact|approximate`), disposition, coupling and evidence status are independent of each other. The word "exact" applies only to the declared operation and its assumptions.

Release checklist:

- Confirm that code is MIT and original documentation, data and fixtures are CC-BY-SA-4.0. Keep inherited terms.
- Freeze the schema, data and operator versions, which are independent of each other, and the compatibility examples.
- Reproduce the pack, CSV, coverage and SHA256SUMS files, and run the installed-package tests on the supported Python versions.
- Run the analytical and adversarial tests. Record the native and host versions and their results separately.
- Audit public artifacts for machine paths, private paths, credentials, out-of-date generated data and unlicensed claims.
- State the unsupported capabilities, resource limits, performance measurements and the artist and semantic gates that remain open.
- Before publishing, confirm the publisher, the release reviewer and the approved source revision. Do not change the byte formats of survey files that consumers inherit.

Since 0.4.0, the implementation is a C++ core (now `msf_character_tools._core`) in place of the removed native pilot. The release wheels in this repository start at 0.5.0. They are for macOS arm64 and for Linux x86_64 and aarch64. These still need separate decisions on scope, owner and effort: more formats, native packages for more operating systems, and production artist acceptance. The current local checks do not pass those release gates.
