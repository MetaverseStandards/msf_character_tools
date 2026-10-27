# Notices

Original Python/C++ source code is licensed MIT. Original documentation, JSON schemas, authoring data, analytical goldens and glTF/GLB fixtures are licensed CC-BY-SA-4.0. Attribution: MSF Tools contributors, 2026. Python fixture generator scripts are code and use MIT; their generated data uses CC-BY-SA-4.0. Exception: the diagnostics registry, `schemas/diagnostics.toml`, is MIT, because the C++ core will generate code from it.

License texts are in [LICENSES](LICENSES). The public glTF specification informs format behavior; its restricted text is not copied into the implementation or fixture assets. Public source evidence appears as factual references with pinned revisions in [docs/sources.md](docs/sources.md). No external sample mesh, GLM, cgltf, JSON library or other third-party runtime code is included in the Python reference.

The C++ extension `msf_tools._core` in built wheels links nanobind 3.1.0 (BSD-3-Clause, copyright 2022 Wenzel Jakob; text in [LICENSES/BSD-3-Clause.txt](LICENSES/BSD-3-Clause.txt)), which includes tsl::robin_map (MIT, copyright 2017 Thibaut Goetghebuer-Planchon; text in [LICENSES/MIT.txt](LICENSES/MIT.txt)). Both license files ship in the wheel. nanobind is fetched at build time and not vendored here.

Existing consumer repositories retain their inherited licenses independently. Installing optional build tools does not add their source code or licenses to this runtime package. The installation backend and interpreter are separately licensed tooling.

The optional `native/ufbx` package (`msf-tools-ufbx`) vendors ufbx 0.23.1 by Samuli Raivio, used under the MIT License option of its dual MIT/Unlicense terms; the full text is in `native/ufbx/vendor/LICENSE.ufbx` and ships in that package. It is built with cffi (MIT). The `msf-tools` package itself contains no ufbx code.

The optional `usd` extra installs usd-core (OpenUSD), which is distributed under the Tomorrow Open Source Technology License 1.0 (TOST-1.0): the Apache License 2.0 with a different Section 6 ("Trademarks"), which grants no permission to use the trade names, trademarks, service marks or product names of the licensor and its affiliates, except as required to comply with Section 4(c) and to reproduce the content of the NOTICE file. msf-tools contains no OpenUSD code. The optional OpenUSD test tier reads OpenUSD's own sample scenes from a local checkout (`MSF_OPENUSD_ASSETS`); they are TOST-1.0 and never committed here.

The examples fetch, and never commit, the Khronos Fox (CC0-1.0 model; CC-BY-4.0 rig, animation and conversion, with the credits in `examples/README.md`), the Khronos AnimatedMorphCube (CC0-1.0) and a Kenney Mini Characters model (CC0-1.0). `examples/data/AnimatedMorphCube.writer.fbx` is AnimatedMorphCube rewritten as FBX by the test writer and stays CC0-1.0.
