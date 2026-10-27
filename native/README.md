# Native code

The pybind11 numerical pilot (`_msf_native`, C++17 kernels under `native/src` and `native/include`) was removed in 0.3.0; the C++ core will replace it. Its sources and contract are in Git history, last at commit 746a5fe.

## ufbx reader for FBX sources (`native/ufbx`)

`native/ufbx` is the separate `msf-tools-ufbx` package used by the FBX adapter. It vendors ufbx 0.23.1 (`vendor/ufbx.c`, `vendor/ufbx.h`, used under its MIT option; see `vendor/LICENSE.ufbx`) and a small C shim (`msf_ufbx_shim.h`/`.c`), built with cffi as the abi3 module `msf_tools_ufbx._native`. `MSF_FBX_SHIM_ABI` in `msf_ufbx_shim.h` must be bumped with any change to the shim's declarations or structs; `msf_tools.sources.fbx.SHIM_ABI` must match it, and `scripts/ci_local.sh` reinstalls the package from the checkout before testing. The pinned commit and file hashes are in `docs/source-lock.json`. ufbx is compiled without stdio, OBJ, geometry caches, subdivision and tessellation, and scenes are only ever loaded from memory with external files off.

```sh
pip install ./native/ufbx      # needs a C compiler; builds and installs msf_tools_ufbx
```

Tests that need it skip when it is not installed. `tests/test_source_fbx_corpus.py` runs over ufbx's own test corpus when `MSF_UFBX_CORPUS` names an extracted ufbx source tree at the pinned commit; the corpus is never committed.
