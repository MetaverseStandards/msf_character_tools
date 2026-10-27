# Building

Original documentation: CC-BY-SA-4.0.

## Build record

Every built package contains `msf_tools/_build_info.json`:

```json
{
  "version": "0.2.0.dev0",
  "commit": "<40 lowercase hex digits>"
}
```

`version` is the package version and `commit` the Git commit the package was built from. RCEF's lock reads this file, and when an install also has Git `vcs_info` in `direct_url.json`, the two commits must agree.

`setup.py` writes the file at build time, so it is never checked in (`.gitignore` lists it):

- A build from the top of a Git checkout records `HEAD` when no tracked file has changed and no untracked file sits under `msf_tools/`, where setuptools would build it into the wheel. This covers `pip install git+...@COMMIT`, `uv pip install`, `uv build` and wheels built from a clean clone.
- Inside a Git checkout only Git counts: a stray `msf_tools/_build_info.json` there is never used.
- Each non-editable build clears `build/lib/msf_tools` first, so a module left there by an earlier build is never shipped under the new record.
- An sdist has no `.git`, so building one writes the record into the sdist. A wheel built from that sdist outside any Git checkout copies it if its version matches.
- Any other build, such as one from a checkout with uncommitted changes or untracked package files, an editable install, or a source tree inside a checkout but not at its top, records no commit and omits the file; non-editable builds print a warning. RCEF then refuses the install, as it does for any install without a source commit.

A checked-in file cannot work, because a commit cannot contain its own hash.

`tests/test_build_info.py` covers these rules with Git's answers faked. `scripts/ci_local.sh` builds a real wheel from a clean clone of `HEAD` through its sdist and checks the record.

## Tools

CMake and Ninja for the C++ core are installed as uv tools under `$MSF/_tools`:

```sh
UV_TOOL_DIR=$MSF/_tools/uv-tools UV_TOOL_BIN_DIR=$MSF/_tools/bin uv tool install cmake
UV_TOOL_DIR=$MSF/_tools/uv-tools UV_TOOL_BIN_DIR=$MSF/_tools/bin uv tool install ninja
```

`scripts/ci_local.sh` puts `$MSF/_tools/bin` first on `PATH` and reports both versions. Nothing builds with them until the C++ core lands. The FBX reader in `native/ufbx` is built with cffi and a C compiler, not CMake.
