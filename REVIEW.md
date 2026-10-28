# Reference implementation review

Original documentation CC-BY-SA-4.0.

One implementation process applied three roles: engineering, math adversary and SDK maintenance. Here, "review" means the implementation's self-review plus concrete feedback from consumer and native peers. It does not mean three independent human reviewers, or adoption as a standard.

## Evidence

- 30 standard-library tests of the public API and CLI pass on Python 3.12.15 and Python 3.11.17. This includes an installed wheel, run outside the checkout.
- The deterministic pack, CSV and coverage goldens pass, and so does the thin check command. Fixture generation uses separate axis equations and is reproducible.
- The original shared combined fixture covers two instances, four nonzero influences, signed relative morph defaults and defaults above 1, and animation times both at authored keys and between them.
- A consumer combined fixture, authored independently, agrees at nine samples. The largest component error seen is 8.2584e-8 m and the RMS error is 2.2237e-8 m, within its 1e-5 m tolerance.
- Consumer teams ran typed profile mappings, structural sidecars, tracking failures and separate tests on real hosts. Read their own evidence before you claim host acceptance.
- The native pilot's numeric and ownership agreement has separate native CTest evidence. Reference acceptance alone is not a native build result.

## Defects found and fixed

1. An unbounded count on a tiny zero-backed accessor. Fix: add explicit budgets for components, objects and resources before allocation, sparse paths included.
2. Sidecar resources were incomplete for sparse accessors. Fix: include the hashes of the indices, the values and the base buffer, with corruption tests.
3. Coverage was too narrow. Fix: keep all the evidence, unused and unresolved sources included, and add profile metadata, partitions by disposition and quality, and totals.
4. The manifest missed extra outputs. Fix: scan the common generation directory that the outputs own, and fail on entries that are not listed.
5. A CLI output alias could overwrite a source. Fix: before any replacement, check resolved paths, hard links and symlink leaf outputs against the authoring, assets and resources. Real negative subprocess tests show that input bytes do not change.
6. The platform's symlink prefix for temporary directories. Fix: resolve output parents, and keep the explicit refusal of a symlink leaf.
7. An unknown required animation extension was refused too early. Fix: list extension targets as inventory, and apply the gate when evaluation is requested.
8. Native and reference acceptance did not agree. Fix: use the same skin weight sum tolerance, 1e-6, with no normalization.
9. Inspection missed binary animation semantics. Fix: validate the type, count, times and rotation keys of available core channels. Unavailable external data stays in the inventory.
10. Hierarchy cycle validation repeated walks up the ancestors. Fix: use a set of completed nodes to bound the traversal across all chains.

11. Fragment discovery could include hidden virtualenv and CI checkouts. Fix: prune generated and hidden files and directories before the traversal, with real tests on fake `.venv`, `.git` and `.ci-tools` directories.

## Remaining gates

The reference supports positions with relative Basis morphs, four-influence LBS, and one core clip that is selected explicitly. These stay explicitly unsupported: non-position geometry, eight influences, DQS, compressed semantics, unsupported required extensions, simultaneous clips and rewriting embedded assets. Resource limits can refuse large assets that are otherwise valid.

These stay separate gates: production artist and contact acceptance, general provider calibration, ownership of external publication, packaging platforms and performance requirements. Scalar mapping quality describes a declared operation under its assumptions. This review claims none of these: universal fidelity, community adoption, security against hostile processes that write to the filesystem at the same time, or a transaction guarantee over many files.
