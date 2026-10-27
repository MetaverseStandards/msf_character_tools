# Notices

Original Python/C++ source code is licensed MIT. Original documentation, JSON schemas, authoring data, analytical goldens and glTF/GLB fixtures are licensed CC-BY-SA-4.0. Attribution: MSF Tools contributors, 2026. Python fixture generator scripts are code and use MIT; their generated data uses CC-BY-SA-4.0.

License texts are in [LICENSES](LICENSES). The public glTF specification informs format behavior; its restricted text is not copied into the implementation or fixture assets. Public source evidence appears as factual references with pinned revisions in [docs/sources.md](docs/sources.md). No external sample mesh, GLM, cgltf, JSON library or other third-party runtime code is included in the Python reference.

Existing consumer repositories retain their inherited licenses independently. Installing optional build tools does not add their source code or licenses to this runtime package. The installation backend and interpreter are separately licensed tooling.

The optional `native/ufbx` package (`msf-tools-ufbx`) vendors ufbx 0.23.1 by Samuli Raivio, used under the MIT License option of its dual MIT/Unlicense terms; the full text is in `native/ufbx/vendor/LICENSE.ufbx` and ships in that package. It is built with cffi (MIT). The `msf-tools` package itself contains no ufbx code.
