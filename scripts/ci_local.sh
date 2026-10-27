#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Run what .github/workflows/check.yml runs, on local Python 3.11 and 3.12
# environments, then print a summary block for a pull-request description.
# Interpreters default to $MSF/_tools/venv3.11 and venv3.12; override with
# MSF_PY311 / MSF_PY312.
set -u
cd "$(dirname "$0")/.." || exit 2
MSF="${MSF:-$HOME/.local/share/msf}"
failed=0
lines=()

seconds() { python3 -c 'import sys, time; print(f"{time.time() - float(sys.argv[1]):.1f}")' "$1"; }

# Reinstall the FBX shim from this checkout first: a stale build loads, then fills fewer fields or crashes.
uv="${UV:-$MSF/_tools/boot/bin/uv}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$MSF/_tools/uv-cache}"
for version in 3.11 3.12; do
  var="MSF_PY${version/./}"
  py="${!var:-$MSF/_tools/venv$version/bin/python}"
  [ -x "$py" ] && "$py" -c 'import cffi' 2>/dev/null || continue
  if [ -x "$uv" ]; then
    install=("$uv" pip install --python "$py" --no-build-isolation --reinstall-package msf-tools-ufbx ./native/ufbx)
  else
    install=("$py" -m pip install --no-build-isolation --no-deps --force-reinstall ./native/ufbx)
  fi
  if "${install[@]}" >/dev/null 2>&1; then
    lines+=("- msf-tools-ufbx for Python $version: reinstalled from native/ufbx")
  else
    lines+=("- msf-tools-ufbx for Python $version: REINSTALL FAILED")
    failed=1
  fi
done

# unittest prints "Ran N tests" and OK/FAILED last; without them the run died part way.
verdict_of() {
  if ! printf '%s\n' "$1" | grep -qE '^Ran '; then echo "CRASHED (no unittest summary, exit $2)"; return; fi
  printf '%s\n' "$1" | grep -E '^(OK|FAILED)' | tail -1
}

for version in 3.11 3.12; do
  var="MSF_PY${version/./}"
  py="${!var:-$MSF/_tools/venv$version/bin/python}"
  if [ ! -x "$py" ]; then
    lines+=("- Python $version: SKIPPED (no interpreter at $py)")
    continue
  fi
  exact=$("$py" -c 'import platform; print(platform.python_version())')
  start=$(python3 -c 'import time; print(time.time())')
  output=$("$py" -B -m unittest discover -s tests 2>&1)
  status=$?
  took=$(seconds "$start")
  ran=$(printf '%s\n' "$output" | grep -E '^Ran ' | tail -1 | cut -d' ' -f2)
  verdict=$(verdict_of "$output" $status)
  if [ $status -ne 0 ] || [ "${verdict#CRASHED}" != "$verdict" ]; then
    failed=1
    printf '%s\n' "$output" | grep -E '^(FAIL|ERROR):' >&2
  fi
  if "$py" -B check.py >/dev/null 2>&1; then check="check.py OK"; else check="check.py FAILED"; failed=1; fi
  lines+=("- Python $exact: unittest ${ran:-?} tests, ${verdict} in ${took} s; $check")
done

# Optional tier on OpenUSD's own sample assets, kept out of the fast suite.
openusd="${MSF_OPENUSD_ASSETS:-$MSF/_viz/assets/openusd}"
py312="${MSF_PY312:-$MSF/_tools/venv3.12/bin/python}"
if [ -f "$openusd/LICENSE.txt" ] && [ -x "$py312" ]; then
  output=$(MSF_OPENUSD_ASSETS="$openusd" "$py312" -B -m unittest discover -s tests -p test_source_openusd.py 2>&1)
  ran=$(printf '%s\n' "$output" | grep -E '^Ran ' | tail -1 | cut -d' ' -f2)
  if printf '%s\n' "$output" | grep -qE '^OK'; then
    lines+=("- OpenUSD assets tier: ${ran:-?} tests OK")
  else
    lines+=("- OpenUSD assets tier: $(verdict_of "$output" 1)")
    printf '%s\n' "$output" | grep -E '^(FAIL|ERROR):' >&2
    failed=1
  fi
else
  lines+=("- OpenUSD assets tier: SKIPPED (no assets at $openusd)")
fi

# Optional tier on ufbx's own FBX corpus, kept out of the fast suite.
corpus="${MSF_UFBX_CORPUS:-$(ls -d "$MSF"/_viz/assets/ufbx/ufbx-26a482ae66871d7de36eb722aa060bce95bce274 2>/dev/null)}"
if [ -n "$corpus" ] && [ -d "$corpus/data" ] && [ -x "$py312" ] && "$py312" -c 'import msf_tools_ufbx' 2>/dev/null; then
  output=$(MSF_UFBX_CORPUS="$corpus" "$py312" -B -m unittest discover -s tests -p 'test_source_fbx_[cd]*.py' 2>&1)
  if printf '%s\n' "$output" | grep -qE '^OK'; then
    lines+=("- ufbx corpus tier (loading, inspection, DCC reference frames): OK")
  else
    lines+=("- ufbx corpus tier: $(verdict_of "$output" 1)")
    printf '%s\n' "$output" | grep -E '^(FAIL|ERROR):' >&2
    failed=1
  fi
else
  lines+=("- ufbx corpus tier: SKIPPED (needs msf-tools-ufbx installed and the corpus under \$MSF/_viz/assets/ufbx)")
fi

# Optional tier: Khronos sample assets re-authored as FBX, kept out of the fast suite.
khronos="${MSF_KHRONOS_ASSETS:-$MSF/_viz/assets/khronos}"
if [ -d "$khronos/Models" ] && [ -x "$py312" ] && "$py312" -c 'import msf_tools_ufbx' 2>/dev/null; then
  output=$(MSF_KHRONOS_ASSETS="$khronos" "$py312" -B -m unittest discover -s tests -p 'test_source_twins.py' 2>&1)
  ran=$(printf '%s\n' "$output" | grep -E '^Ran ' | tail -1 | cut -d' ' -f2)
  if printf '%s\n' "$output" | grep -qE '^OK'; then
    lines+=("- Khronos FBX twins tier: ${ran:-?} tests OK")
  else
    lines+=("- Khronos FBX twins tier: $(verdict_of "$output" 1)")
    printf '%s\n' "$output" | grep -E '^(FAIL|ERROR):' >&2
    failed=1
  fi
else
  lines+=("- Khronos FBX twins tier: SKIPPED (needs msf-tools-ufbx and \$MSF/_viz/assets/khronos)")
fi

# Optional tier: the 09K real-asset harness recipes, one test per CASE_MATRIX ID.
real="${MSF_REAL_ASSETS:-$MSF/_viz/assets/real09K}"
if [ -f "$real/real-asset-harness-plan09K/CASE_MATRIX.json" ] && [ -x "$py312" ]; then
  output=$(MSF_REAL_ASSETS="$real" "$py312" -B -m unittest discover -s tests -p 'test_real_assets.py' 2>&1)
  ran=$(printf '%s\n' "$output" | grep -E '^Ran ' | tail -1 | cut -d' ' -f2)
  if printf '%s\n' "$output" | grep -qE '^OK'; then
    lines+=("- Real-asset recipe tier: ${ran:-?} tests, $(printf '%s\n' "$output" | grep -E '^OK' | tail -1)")
  else
    lines+=("- Real-asset recipe tier: $(verdict_of "$output" 1)")
    printf '%s\n' "$output" | grep -E '^(FAIL|ERROR):' >&2
    failed=1
  fi
else
  lines+=("- Real-asset recipe tier: SKIPPED (no 09K inputs at $real)")
fi

if ! command -v cmake >/dev/null 2>&1; then
  lines+=("- Native pilot: SKIPPED (cmake not found)")
elif ! command -v c++ >/dev/null 2>&1; then
  lines+=("- Native pilot: SKIPPED (no C++ compiler)")
else
  build=$(mktemp -d)
  if cmake -S . -B "$build" -DMSF_BUILD_NATIVE_PILOT=ON >/dev/null \
      && cmake --build "$build" --config Release >/dev/null \
      && ctest --test-dir "$build" -C Release --output-on-failure >/dev/null; then
    lines+=("- Native pilot: build and ctest OK")
  else
    lines+=("- Native pilot: FAILED (rerun cmake/ctest in $build for details)")
    failed=1
  fi
  [ $failed -eq 0 ] && rm -rf "$build"
fi

commit=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)
dirty=$(git status --porcelain --untracked-files=no 2>/dev/null | grep -q . && echo ", uncommitted changes" || true)
echo
echo "### Local checks (scripts/ci_local.sh)"
echo "- Commit: $commit on $branch$dirty; $(uname -sm)"
printf '%s\n' "${lines[@]}"
[ $failed -eq 0 ] && echo "- Result: all run checks passed" || echo "- Result: FAILED"
exit $failed
