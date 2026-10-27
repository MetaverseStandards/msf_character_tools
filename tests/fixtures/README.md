# Original combined reference fixture

Original assets, analytical goldens and documentation: **CC-BY-SA-4.0**, authorship **MSF Tools contributors (2026)**. Attribution: “MSF Tools combined reference fixture”, with the license link https://creativecommons.org/licenses/by-sa/4.0/. Generator source is MIT code. No third-party mesh, textures, rigs or captured tracking are included.

`combined.gltf` embeds its binary buffer. `combined.glb` has equivalent core data plus original opaque chunk type0xDEADBEEF. All geometry is original six-vertex head/accessory proxy geometry, with four nonzero influences (.4,.3,.2,.1), relative wink.L/smile/jawSmileCorrective morphs, signed/>1 defaults, head Y/jaw X/root Z transforms and accessory translation. Unknown weighted joint remains in the palette. Two instances node5/node6 use mesh0 with distinct transforms/default drivers.

Clip `CombinedReference` index0 spans0..2 seconds. Node5 morph weights animate; node6 retains authored defaults. `combined.analytical.json` records eight explicit times including intermediates/end clamp. Direct rotation equations in `../make_fixtures.py` construct goldens independently; root rotation cancels through per-instance mesh world inverse. `rest-not-bind.gltf` changes rest head translation without changing inverse bind matrices. `eight-influence.gltf` adds a second influence set with zero weights and must evaluate exactly like `combined.gltf`.

`eight-weighted.gltf` binds two points to eight joints each, with nonzero weights split across `JOINTS_0`/`WEIGHTS_0` and `JOINTS_1`/`WEIGHTS_1`; its expected positions follow from the joint translations and one quarter turn, computed directly in the test.

`native-agreement.gltf` is a one-vertex skinned, morphed and animated asset with two instances of one mesh. `native/tests/test_agreement.py` and `test_core_semantics.py` both read it.

Regenerate using `python -B tests/make_fixtures.py`. Fixtures are intentionally small analytical examples, not artist acceptance assets. The source topology/opaque data remains untouched by inspection and sidecar annotation.

## Synthetic USD fixtures

`source/` holds original synthetic USDA scenes for the USD strict tier, one per case: skinned and animated rigs (Y-up metres and Z-up centimetres), dual-quaternion skinning, eight and constant influences, left-handed faces, an n-gon with a hole, a default subdivision cage, an in-between shape, shear on a static leaf, an interior node and an animated node, a rotated, uniformly scaled interior node, a mirrored node, negative time codes, instancing, a point instancer, sublayer/reference/payload layers under `source/layers/`, and an escaping sublayer. Same license and authorship as above. Regenerate with `python -B tests/make_source_fixtures.py`.
