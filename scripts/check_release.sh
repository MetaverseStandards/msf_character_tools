#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Check the distributions scripts/build_release.sh wrote, against the commit they
# were built from:
#   - each wheel holds exactly the commit's msf_character_tools/*.py, one _core extension,
#     the build record naming the commit, and the licence files pyproject lists;
#   - macOS: the extension links only system libraries and targets macOS 11.0;
#   - Linux: auditwheel show finds the manylinux_2_28 tag for this machine's
#     architecture, nothing was vendored, and the extension needs only the C and
#     C++ runtime libraries the policy allows;
#   - each wheel installs, with the usd extra, into a fresh venv on its interpreter,
#     imports its own extension, and passes the public suite there, unchanged;
#   - the sdist carries docs/, schemas/ and the licences but no tests or examples.
#
#   scripts/check_release.sh DIST [COMMIT]
#
# Interpreters as in scripts/build_release.sh; MSF_PY313 (optional) also runs the
# abi3 wheel on a newer CPython.
set -u
dist=$(cd "${1:?usage: scripts/check_release.sh DIST [COMMIT]}" && pwd)
cd "$(dirname "$0")/.." || exit 2
commit=$(git rev-parse --verify -q "${2:-HEAD}^{commit}") || { echo "not a commit: ${2:-HEAD}" >&2; exit 2; }
MSF="${MSF:-}"
if [ -n "$MSF" ]; then
  uv="${UV:-$MSF/_tools/boot/bin/uv}"
  py311="${MSF_PY311:-$MSF/_tools/venv3.11/bin/python}"
  py312="${MSF_PY312:-$MSF/_tools/venv3.12/bin/python}"
else
  uv="${UV:-$(command -v uv)}"
  py311="${MSF_PY311:-$(command -v python3.11)}"
  py312="${MSF_PY312:-$(command -v python3.12)}"
fi
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
failed=0
note() { echo "$1"; case "$1" in *FAIL*) failed=1 ;; esac; }

git archive "$commit" | tar -x -C "$scratch" --one-top-level=src 2>/dev/null || { mkdir "$scratch/src"; git archive "$commit" | tar -x -C "$scratch/src"; }
"$py312" -I - "$dist" "$commit" "$scratch/src" <<'PY' || failed=1
import json, sys, tarfile, tomllib, zipfile
from pathlib import Path
dist, commit, src = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
project = tomllib.loads((src / 'pyproject.toml').read_text())['project']
version = project['version']
modules = {str(p.relative_to(src)) for p in (src / 'msf_character_tools').rglob('*.py')}
licences = {f'msf_character_tools-{version}.dist-info/licenses/{name}' for name in project['license-files']}
ok = True
for wheel in sorted(dist.glob('*.whl')):
    # auditwheel repair adds directory entries; only files count.
    names = {n for n in zipfile.ZipFile(wheel).namelist() if not n.endswith('/')}
    package = {n for n in names if n.startswith('msf_character_tools/')}
    extension = {n for n in package if n.startswith('msf_character_tools/_core.')}
    record = json.loads(zipfile.ZipFile(wheel).read('msf_character_tools/_build_info.json'))
    found = {n for n in names if '/licenses/' in n}
    checks = {'build record': record == {'version': version, 'commit': commit},
              'one extension': len(extension) == 1,
              'only tracked modules': package == modules | extension | {'msf_character_tools/_build_info.json'},
              'licence files': found == licences}
    for name, good in checks.items():
        print(f"{wheel.name}: {name} {'ok' if good else 'FAILED'}")
        ok &= good
[sdist] = dist.glob('*.tar.gz')
with tarfile.open(sdist) as archive:
    top = {n.split('/')[1] for n in archive.getnames() if n.count('/') >= 1}
    info = archive.extractfile(f'msf_character_tools-{version}/PKG-INFO').read().decode()
good = {'docs', 'schemas', 'LICENSES', 'core', 'msf_character_tools'} <= top and not top & {'tests', 'examples', 'scripts', 'native'}
good &= f"License-Expression: {project['license']}" in info
print(f"{sdist.name}: contents and licence metadata {'ok' if good else 'FAILED'}")
sys.exit(not (ok and good))
PY

if [ "$(uname -s)" = Linux ]; then
  "$uv" venv -q --python "$py312" "$scratch/audit" && "$uv" pip install -q --python "$scratch/audit/bin/python" auditwheel
  arch=$(uname -m)
  for wheel in "$dist"/*-manylinux_*_"$arch".whl; do
    name=$(basename "$wheel")
    shown=$("$scratch/audit/bin/auditwheel" show "$wheel" 2>&1)
    case "$name" in *"manylinux_2_28_$arch.whl") ;; *) note "$name: tag is not manylinux_2_28_$arch, FAILED" ;; esac
    # auditwheel show names the oldest policy the wheel meets; manylinux_2_28 needs it to be 2_28 or older.
    oldest=$(printf '%s' "$shown" | tr '\n' ' ' | sed -n "s/.*consistent with the following platform tag: \"manylinux_2_\([0-9]*\)_$arch\".*/\1/p")
    if [ -n "$oldest" ] && [ "$oldest" -le 28 ]; then
      note "$name: auditwheel show: meets manylinux_2_${oldest}_$arch, so manylinux_2_28_$arch holds"
    else
      note "$name: auditwheel show FAILED: $(printf '%s' "$shown" | tr '\n' ' ')"
    fi
    if unzip -l "$wheel" | grep -q '\.libs/'; then note "$name: auditwheel vendored libraries, FAILED"; fi
    tags=$(unzip -p "$wheel" '*.dist-info/WHEEL' | grep -c '^Tag:')
    [ "$tags" = 1 ] || note "$name: $tags wheel tags, FAILED (want exactly one)"
    mkdir -p "$scratch/whl" && rm -rf "$scratch/whl"/* && (cd "$scratch/whl" && unzip -q "$wheel")
    needed=$(readelf -d "$scratch/whl"/msf_character_tools/_core.*.so | sed -n 's/.*(NEEDED).*\[\(.*\)\]/\1/p' | sort | tr '\n' ' ')
    others=$(printf '%s' "$needed" | tr ' ' '\n' | grep -vE '^(libstdc\+\+\.so\.6|libm\.so\.6|libgcc_s\.so\.1|libc\.so\.6|libpthread\.so\.0|libdl\.so\.2|ld-linux.*)?$' || true)
    [ -z "$others" ] && note "$name: needs only $needed" || note "$name: needs other libraries, FAILED: $others"
  done
else
  for wheel in "$dist"/*macosx*.whl; do
    mkdir -p "$scratch/whl" && rm -rf "$scratch/whl"/* && (cd "$scratch/whl" && unzip -q "$wheel")
    so=$(ls "$scratch/whl"/msf_character_tools/_core.*.so)
    others=$(otool -L "$so" | tail -n +2 | awk '{print $1}' | grep -vE '^(/usr/lib/|/System/Library/)' || true)
    [ -z "$others" ] && note "$(basename "$wheel"): links only system libraries ($(otool -L "$so" | tail -n +2 | awk '{print $1}' | tr '\n' ' '))" \
      || note "$(basename "$wheel"): non-system libraries FAILED: $others"
    minos=$(otool -l "$so" | awk '/LC_BUILD_VERSION/{f=1} f&&/minos/{print $2; exit}')
    [ "$minos" = 11.0 ] && note "$(basename "$wheel"): targets macOS $minos" || note "$(basename "$wheel"): targets macOS $minos, FAILED (want 11.0)"
  done
fi

# The public suite asserts that msf_character_tools is the one next to tests/, so the tests
# go next to the installed package, in the throwaway venv's site-packages.
run_public() {
  local py=$1 wheel=$2 venv="$scratch/venv-$(basename "$1")"
  [ -f "$wheel" ] || { note "no single wheel for $py on this platform in $dist: FAILED"; return; }
  rm -rf "$venv"
  "$uv" venv -q --python "$py" "$venv" && "$uv" pip install -q --python "$venv/bin/python" "msf-character-tools[usd] @ file://$wheel" || { note "$(basename "$wheel") on $py: install FAILED"; return; }
  local site
  site=$("$venv/bin/python" -I -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')
  cp -R "$scratch/src/tests" "$scratch/src/schemas" "$scratch/src/examples" "$site/"
  local version file
  version=$("$venv/bin/python" -I -c 'import platform; print(platform.python_version())')
  file=$(cd / && "$venv/bin/python" -I -c 'from msf_character_tools import _native; print(_native.built.__file__)')
  case "$file" in "$site"/msf_character_tools/_core.*) ;; *) note "$(basename "$wheel") on $version: imported $file, FAILED"; return ;; esac
  local output
  output=$(cd / && MSF_REQUIRE_FORMATS=fbx,usd "$venv/bin/python" -I -B -m unittest discover -s "$site/tests/public" -t "$site/tests/public" 2>&1)
  if printf '%s\n' "$output" | grep -qE '^OK'; then
    note "$(basename "$wheel") on Python $version: installed, loads $(basename "$file"), public suite $(printf '%s\n' "$output" | grep -E '^Ran' | cut -d' ' -f2) tests $(printf '%s\n' "$output" | grep -E '^OK')"
  else
    printf '%s\n' "$output" | grep -E '^(FAIL|ERROR):' >&2
    note "$(basename "$wheel") on Python $version: public suite FAILED"
  fi
}
# Only this machine's wheels can be installed, so a folder with every platform's wheels also works.
if [ "$(uname -s)" = Linux ]; then plat="manylinux_*_$(uname -m)"; else plat="macosx_*"; fi
run_public "$py311" "$(ls "$dist"/*-cp311-cp311-$plat.whl 2>/dev/null)"
run_public "$py312" "$(ls "$dist"/*-cp312-abi3-$plat.whl 2>/dev/null)"
[ -n "${MSF_PY313:-}" ] && run_public "$MSF_PY313" "$(ls "$dist"/*-cp312-abi3-$plat.whl 2>/dev/null)"
[ $failed -eq 0 ] && echo "Result: all release checks passed" || echo "Result: FAILED"
exit $failed
