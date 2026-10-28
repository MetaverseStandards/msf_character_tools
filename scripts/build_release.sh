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
# machine's architecture (MSF_MANYLINUX_IMAGE, by default the image pinned by
# digest below, run with MSF_PODMAN, default podman) with its /opt/python cp311
# and cp312, then tagged by auditwheel repair; the image and its digest are
# written to BUILD-ENV next to SHA256SUMS. The container builds offline: the host
# downloads the build requirements into a wheelhouse first (through HTTPS_PROXY
# when that is set). The sdist is built on the host with MSF_PY312 either way.
# Build requirements come from scripts/build-requirements.txt, with hashes required.
# Needs uv (UV, or on PATH, or $MSF/_tools/boot/bin/uv).
set -eu
requirements=$(cd "$(dirname "$0")" && pwd)/build-requirements.txt
mkdir -p "${1:?usage: scripts/build_release.sh OUTDIR [COMMIT]}"
out=$(cd "$1" && pwd)
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
pinned=(--build-constraints "$requirements" --require-hashes)
(cd "$scratch/src" && "$uv" build -q --sdist --python "$py312" "${pinned[@]}" --out-dir "$out")
sdist=$(ls "$out"/msf_tools-*.tar.gz)
# Wheels come from the unpacked sdist, outside any Git checkout, as a user's build would.
mkdir "$scratch/unpacked"
tar -xzf "$sdist" -C "$scratch/unpacked"
if [ "$(uname -s)" = Linux ]; then
  case "$(uname -m)" in
    x86_64) digest=sha256:e0adf18521ad35192df733a6c62d35df7801957d24e0470238aacecfab2188a3 ;;
    aarch64) digest=sha256:a3e02308c822fb6ce0d12248b0c941817ba5e1a1bc9e7bb5929f29c50eaa40a9 ;;
    *) echo "no manylinux_2_28 image for $(uname -m)" >&2; exit 1 ;;
  esac
  image="${MSF_MANYLINUX_IMAGE:-quay.io/pypa/manylinux_2_28_$(uname -m)@$digest}"
  "$uv" venv -q --seed --python "$py312" "$scratch/download"
  # The container installs build requirements only from this wheelhouse, so the hashes checked here hold there.
  for version in 3.11 3.12; do
    "$scratch/download/bin/python" -m pip download -q --require-hashes --only-binary=:all: \
      --platform "manylinux_2_28_$(uname -m)" --platform "manylinux_2_17_$(uname -m)" --platform "manylinux_2_12_$(uname -m)" \
      --python-version "$version" -d "$scratch/wheelhouse" -r "$requirements"
  done
  # Word splitting is wanted: MSF_PODMAN may carry podman's own options.
  # shellcheck disable=SC2086
  ${MSF_PODMAN:-podman} run --rm --network none -v "$scratch:/io" -e SOURCE_DATE_EPOCH "$image" bash -euc '
      for py in cp311-cp311 cp312-cp312; do
        (cd /io/unpacked/msf_tools-* && /opt/python/$py/bin/python -m pip wheel -q --no-deps --no-index --find-links /io/wheelhouse -w /io/raw .)
      done
      # One platform tag only: lock files (RCEF'"'"'s) key a wheel by its single tag.
      for wheel in /io/raw/*.whl; do
        auditwheel repair --plat "manylinux_2_28_$(uname -m)" --only-plat -w /io/repaired "$wheel" >/dev/null 2>&1
      done
      { echo "os $(cat /etc/os-release | grep ^PRETTY_NAME | cut -d= -f2) $(auditwheel --version | head -1 | cut -d" " -f1,2)"; gcc --version | head -1; } > /io/toolchain.txt'
  cp "$scratch"/repaired/*.whl "$out"/
  { echo "image $image $(${MSF_PODMAN:-podman} image inspect --format '{{.Digest}}' "$image")"
    cat "$scratch/toolchain.txt"; } > "$out/BUILD-ENV"
  cat "$out/BUILD-ENV"
else
  for py in "$py311" "$py312"; do
    (cd "$scratch/unpacked"/msf_tools-* && "$uv" build -q --wheel --python "$py" "${pinned[@]}" --out-dir "$out")
  done
fi
sha256() { if command -v sha256sum >/dev/null; then sha256sum "$@"; else shasum -a 256 "$@"; fi; }
(cd "$out" && sha256 msf_tools-* > SHA256SUMS && cat SHA256SUMS)
echo "commit $commit, SOURCE_DATE_EPOCH $SOURCE_DATE_EPOCH"
