# Contributing

Original documentation: CC-BY-SA-4.0.

Use Python 3.11 or later and the standard library for the reference. When you open a change, describe a concrete input and its output. Give the licence and provenance of any new data, and list the checks you ran. Keep signal meaning and calibration explicit. Evidence that is not resolved can stay listed as inventory. A new dependency needs a measured need and a licence review.

Before a change is accepted:

1. Run the reference tests and the generated-byte checks on Python 3.11 and 3.12.
2. For changes to transforms, operators or curves, add expected values that you calculate independently. Do not make expected values by calling the implementation under test.
3. Review the behaviour on malformed input. Check that failures return a Result with no value, that asset bytes do not change, and check sidecar hashes and output aliases.
4. For wire changes, update the schemas and the reference. An incompatible contract change needs version and migration notes, and compatibility fixtures.
5. Keep original licences and source attributions. For each claim taken from a public source, give the source revision, digest and locator.
6. Record the gates that remain open, honestly. This includes runs on real hosts and native runs, and visual or contact review where it applies.

Use the review tools of the repository host when the publisher supplies them. This document does not imply external community channels or named human maintainers. A local reference change that can be reverted can be reviewed before publication. Release and remote ownership follow the repository governance.
