# Notices

Original Python and C++ source code is licensed MIT. Original documentation, JSON schemas, authoring data, analytical goldens and glTF/GLB fixtures are licensed CC-BY-SA-4.0. Attribution: MSF Tools contributors, 2026. The Python scripts that generate fixtures are code and use MIT. The data they generate uses CC-BY-SA-4.0. There are two exceptions. The diagnostics registry, `schemas/diagnostics.toml`, is MIT, because the C++ core generates code from it. `tests/public/fixtures/simple-skin.gltf` is a third-party asset, described below.

Distributions: the sdist holds the code, `docs/` and `schemas/`. The wheel holds the `msf_tools` package and its C++ extension, with the README as its description. Their licence expression, `MIT AND BSD-3-Clause AND BSL-1.0 AND PSF-2.0 AND CC-BY-SA-4.0`, covers both. Tests and examples are in neither.

Licence texts are in [LICENSES](LICENSES). The public glTF specification informs the format behaviour. Its restricted text is not copied into the implementation or the fixture assets. Public source evidence appears as factual references with pinned revisions in [docs/sources.md](docs/sources.md). Apart from the third-party code listed below, the package includes no GLM, cgltf, JSON library or other third-party runtime code.

Two external sample meshes are committed:
- The test fixture `tests/public/fixtures/simple-skin.gltf` is the Khronos SimpleSkin sample (glTF-Embedded) by Marco Hutter, CC0-1.0. It is copied unchanged from KhronosGroup/glTF-Sample-Assets commit 8f492390ddc7a2ae221a1369ef560589cf8c70fb. The CC0-1.0 text is in [LICENSES/CC0-1.0.txt](LICENSES/CC0-1.0.txt).
- `examples/data/AnimatedMorphCube.writer.fbx`, described at the end of this file.

Tests and examples are left out of the sdist and the wheel, so neither contains these files.

In built wheels, the C++ extension `msf_tools._core` links nanobind 3.1.0 (BSD-3-Clause, copyright 2022 Wenzel Jakob; text in [LICENSES/BSD-3-Clause.txt](LICENSES/BSD-3-Clause.txt)). nanobind includes tsl::robin_map (MIT, copyright 2017 Thibaut Goetghebuer-Planchon; its own text in [LICENSES/robin_map-MIT.txt](LICENSES/robin_map-MIT.txt)). Both licence files ship in the wheel. nanobind is fetched at build time and is not vendored here.

The C++ core vendors three libraries under `core/third_party`, each with its licence files. All three are compiled into the extension:

- Ryu by Ulf Adams, commit 4c0618b0e44f7ef027ebae05d2cc7812048f7c8f (`ryu/`: the shortest float64 formatter). It is used under the Boost Software License 1.0 option of its Apache-2.0 OR BSL-1.0 terms. The text is in [LICENSES/BSL-1.0.txt](LICENSES/BSL-1.0.txt).
- fast_float by Daniel Lemire and contributors, v8.3.2 (`fast_float/`: the float parser). It is used under the MIT option of its Apache-2.0 OR BSL-1.0 OR MIT terms. Its copyright notice is in `core/third_party/fast_float/LICENSE-MIT`.
- ufbx 0.23.1 by Samuli Raivio, commit 26a482ae66871d7de36eb722aa060bce95bce274 (`ufbx/`: the FBX reader). It is used under the MIT License option of its dual MIT/Unlicense terms. The text is in [LICENSES/ufbx-MIT.txt](LICENSES/ufbx-MIT.txt) and `core/third_party/ufbx/LICENSE.ufbx`. There is one local change, marked in `ufbx.c` and recorded in `docs/source-lock.json`: `ufbxi_f64_to_i64` compares with `<` instead of `<=`, so 2^63 saturates instead of overflowing `int64_t`. Our C shim over ufbx, `core/src/msf_ufbx_shim.c`, is MIT.

Two functions in `core/src/math3d.cpp` are derived from `Modules/mathmodule.c` in CPython 3.12.15 (tag v3.12.15, commit e848e4b09ca4bc67c0041c9ce7526dae471d4c36). They make results match `math.hypot` and `math.fsum` bit for bit. `hypot` is derived from `vector_norm()`. The special-value handling and final rounding of `fsum` are derived from `math_fsum()`. Changes: translated to C++ and, for `fsum`, applied to an array instead of an iterator. They are used under the Python Software Foundation License Version 2, whose text is in [LICENSES/PSF-2.0.txt](LICENSES/PSF-2.0.txt): Copyright (c) 2001, 2002, 2003, 2004, 2005, 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023 Python Software Foundation; All Rights Reserved.

Existing consumer repositories keep their inherited licences, independently of this one. Installing optional build tools does not add their source code or licences to this runtime package. The installation backend and the interpreter are tools with their own licences.

The optional `usd` extra installs usd-core (OpenUSD), which is distributed under the Tomorrow Open Source Technology License 1.0 (TOST-1.0). TOST-1.0 is the Apache License 2.0 with a different Section 6 ("Trademarks"). That section grants no permission to use the trade names, trademarks, service marks or product names of the licensor and its affiliates, except as required to comply with Section 4(c) and to reproduce the content of the NOTICE file. msf-tools contains no OpenUSD code. The optional OpenUSD test tier reads OpenUSD's own sample scenes from a local checkout (`MSF_OPENUSD_ASSETS`). Those scenes are TOST-1.0 and are never committed here.

The examples fetch, and never commit, these assets:
- the Khronos Fox (CC0-1.0 model; CC-BY-4.0 rig, animation and conversion, with the credits in `examples/README.md`);
- the Khronos AnimatedMorphCube (CC0-1.0);
- a Kenney Mini Characters model (CC0-1.0).

`examples/data/AnimatedMorphCube.writer.fbx` is AnimatedMorphCube rewritten as FBX by the test writer, and stays CC0-1.0.
