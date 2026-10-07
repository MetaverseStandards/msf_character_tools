# Bounded native numerical pilot

Original MIT C++17 common, expression and skeletal kernels use binary64 and owned values. Public interfaces contain no third-party types. Asset parsing, preservation reports, evidence validation and mapping compilation remain in the Python reference. The native scalar program receives already-resolved, topologically ordered instructions; it is not an authoring compiler.

The pilot implements affine transforms and inverse, TRS validation with shear/singularity rejection, shortest-path quaternion slerp, duration-scaled Hermite curves, relative position morphs, conventional four-influence LBS with mesh-instance inverse and scalar identity/affine/weighted-sum operations. Skin weights must sum to one within `1e-6`; they are not silently normalized. Morph weights may be signed or exceed one.

```sh
cmake -S . -B build -DMSF_BUILD_NATIVE_PILOT=ON
cmake --build build
ctest --test-dir build --output-on-failure
```

Optional Python bindings require pybind11 3.1 and Python development headers. Set `MSF_BUILD_PYTHON_BINDINGS=ON` and provide `pybind11_DIR` if needed. This adds an independent generated glTF fixture comparing native kernels with the public Python geometry evaluator at intermediate curve times, signed/large morph weights and multiple mesh instances. Ownership and invalid tracking tests also run.

No GLM, JSON or glTF parser dependency is needed for this bounded numerical pilot. Future native asset parsing may select the previously reviewed private dependencies after preservation and consumer gates. No stable cross-version ABI or three-platform wheel support is claimed. The tested host and toolchain are recorded in the implementation status.
