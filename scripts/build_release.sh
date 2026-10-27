#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Build the release distributions from a clean clone of a commit: the sdist, then
# each wheel from that sdist, with SOURCE_DATE_EPOCH set to the commit's time so
# that rebuilding the same commit gives the same bytes. Prints SHA256SUMS.
#
#   scripts/build_release.sh OUTDIR [COMMIT]
#
# On macOS the wheels are built for MSF_PY311 (cp311) and MSF_PY312 (cp312-abi3),
# by default python3.11 and python3.12 on PATH, or the venvs in the local
# workspace $MSF. On Linux they are built in the manylinux_2_28 container for the
# machine's architecture (MSF_MANYLINUX_IMAGE, run with MSF_PODMAN, default
# podman) with its /opt/python cp311 and cp312, then tagged by auditwheel repair;
# the container reaches PyPI for the build requirements through HTTPS_PROXY when
# that is set. The sdist is built on the host with MSF_PY312 either way.
# Needs uv (UV, or on PATH, or $MSF/_tools/boot/bin/uv).
set -eu
out=$(cd "$(dirname "${1:?usage: scripts/build_release.sh OUTDIR [COMMIT]}")" && pwd)/$(basename "$1")
commit=$(git -C "$(dirname "$0")/.." rev-parse "${2:-HEAD}")
MSF="${MSF:-}"
if [ -n "$MSF" ]; then
  export PATH="$MSF/_tools/bin:$PATH"
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
git clone -q --no-hardlinks "$(dirname "$0")/.." "$scratch/src"
git -C "$scratch/src" checkout -q "$commit"
SOURCE_DATE_EPOCH=$(git -C "$scratch/src" log -1 --format=%ct)
export SOURCE_DATE_EPOCH
mkdir -p "$out"
(cd "$scratch/src" && "$uv" build -q --sdist --python "$py312" --out-dir "$out")
sdist=$(ls "$out"/msf_tools-*.tar.gz)
# Wheels come from the unpacked sdist, outside any Git checkout, as a user's build would.
mkdir "$scratch/unpacked"
tar -xzf "$sdist" -C "$scratch/unpacked"
if [ "$(uname -s)" = Linux ]; then
  image="${MSF_MANYLINUX_IMAGE:-quay.io/pypa/manylinux_2_28_$(uname -m)}"
  # Word splitting is wanted: MSF_PODMAN may carry podman's own options.
  # shellcheck disable=SC2086
  ${MSF_PODMAN:-podman} run --rm --network host -v "$scratch:/io" -e SOURCE_DATE_EPOCH \
    -e HTTPS_PROXY="${HTTPS_PROXY:-}" -e HTTP_PROXY="${HTTP_PROXY:-}" -e https_proxy="${HTTPS_PROXY:-}" -e http_proxy="${HTTP_PROXY:-}" \
    "$image" bash -euc '
      for py in cp311-cp311 cp312-cp312; do
        (cd /io/unpacked/msf_tools-* && /opt/python/$py/bin/python -m pip wheel -q --no-deps -w /io/raw .)
      done
      for wheel in /io/raw/*.whl; do auditwheel repair -w /io/repaired "$wheel" >/dev/null; done
      { echo "image $(cat /etc/os-release | grep ^PRETTY_NAME | cut -d= -f2) $(auditwheel --version)"; gcc --version | head -1; } > /io/toolchain.txt'
  cp "$scratch"/repaired/*.whl "$out"/
  cat "$scratch/toolchain.txt"
  echo "image $image $(${MSF_PODMAN:-podman} image inspect --format '{{.Digest}}' "$image")"
else
  for py in "$py311" "$py312"; do
    (cd "$scratch/unpacked"/msf_tools-* && "$uv" build -q --wheel --python "$py" --out-dir "$out")
  done
fi
sha256() { if command -v sha256sum >/dev/null; then sha256sum "$@"; else shasum -a 256 "$@"; fi; }
(cd "$out" && sha256 msf_tools-* > SHA256SUMS && cat SHA256SUMS)
echo "commit $commit, SOURCE_DATE_EPOCH $SOURCE_DATE_EPOCH"
