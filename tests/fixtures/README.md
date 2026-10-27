# Original combined reference fixture

Original assets, analytical goldens and documentation: **CC-BY-SA-4.0**, authorship **MSF Tools contributors (2026)**. Attribution: “MSF Tools combined reference fixture”, with the license link https://creativecommons.org/licenses/by-sa/4.0/. Generator source is MIT code. No third-party mesh, textures, rigs or captured tracking are included.

`combined.gltf` embeds its binary buffer. `combined.glb` has equivalent core data plus original opaque chunk type0xDEADBEEF. All geometry is original six-vertex head/accessory proxy geometry, with four nonzero influences (.4,.3,.2,.1), relative wink.L/smile/jawSmileCorrective morphs, signed/>1 defaults, head Y/jaw X/root Z transforms and accessory translation. Unknown weighted joint remains in the palette. Two instances node5/node6 use mesh0 with distinct transforms/default drivers.

Clip `CombinedReference` index0 spans0..2 seconds. Node5 morph weights animate; node6 retains authored defaults. `combined.analytical.json` records eight explicit times including intermediates/end clamp. Direct rotation equations in `../make_fixtures.py` construct goldens independently; root rotation cancels through per-instance mesh world inverse. `rest-not-bind.gltf` changes rest head translation without changing inverse bind matrices. `eight-influence.gltf` inventories second influence arrays and must reject requested evaluation.

`native-agreement.gltf` is a one-vertex skinned, morphed and animated asset with two instances of one mesh. `native/tests/test_agreement.py` and `test_core_semantics.py` both read it.

`simple-skin.gltf` is the Khronos **SimpleSkin** sample (glTF-Embedded) by Marco Hutter, **CC0-1.0**, copied unchanged from KhronosGroup/glTF-Sample-Assets commit 8f492390ddc7a2ae221a1369ef560589cf8c70fb. Its rotation keys are up to 2.3e-4 off unit length, which glTF-Validator accepts. It is not generated.

Regenerate the other fixtures using `python -B tests/make_fixtures.py`. Fixtures are intentionally small analytical examples, not artist acceptance assets. The source topology/opaque data remains untouched by inspection and sidecar annotation.
