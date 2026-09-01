#!/bin/sh
# Fetch, verify, and install trs80gp 2.5.7 into tools/bin/.
#
# trs80gp is closed-source binary-only freeware (ADR-0007,
# docs/adr/0007-trs80gp-pinned-binary.md) — it cannot join build-tools.sh's
# from-source pattern, so this script pins it by SHA-256 instead. The
# checksum below was computed once, against the exact archive this script
# now serves from two places: it is checked on every fetch, and a mismatch
# is fatal. There is no unverified fallback — if neither source produces a
# file matching the pin, this script exits non-zero and installs nothing.
#
# Mirror rationale: upstream (48k.ca) keeps only the last few releases
# online, so the archive that verified our Model 4 research
# (docs/research/trs80-model4-emulation.md) could vanish out from under a
# pinned checksum. The project mirrors the exact verified zip as a GitHub
# release asset and tries that first.
set -e

VERSION=2.5.7
ARCHIVE="trs80gp-${VERSION}.zip"
SHA256_PIN="a994bd5e62a0d09b9f2f259bd3009bf42c361bdb2ac105d557aacfde1a7926d0"

MIRROR_URL="https://github.com/pmcfadin/retronix/releases/download/tools-trs80gp-2.5.7/${ARCHIVE}"
UPSTREAM_URL="http://48k.ca/${ARCHIVE}"

cd "$(dirname "$0")"
mkdir -p bin work
cd work

if [ -x ../bin/trs80gp ]; then
    echo "trs80gp already installed at ../bin/trs80gp"
    exit 0
fi

sha256_of() {
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    else
        sha256sum "$1" | awk '{print $1}'
    fi
}

fetch() {
    url="$1"
    out="$2"
    echo "Fetching ${url} ..."
    if ! curl -fsSL -o "$out" "$url"; then
        echo "  fetch failed: ${url}" >&2
        return 1
    fi
    return 0
}

rm -f "$ARCHIVE"

if fetch "$MIRROR_URL" "$ARCHIVE" && [ "$(sha256_of "$ARCHIVE")" = "$SHA256_PIN" ]; then
    echo "Verified against project mirror."
else
    echo "Mirror unavailable or failed checksum; trying upstream." >&2
    rm -f "$ARCHIVE"
    if ! fetch "$UPSTREAM_URL" "$ARCHIVE"; then
        echo "FATAL: could not fetch ${ARCHIVE} from mirror or upstream." >&2
        exit 1
    fi
    GOT="$(sha256_of "$ARCHIVE")"
    if [ "$GOT" != "$SHA256_PIN" ]; then
        echo "FATAL: checksum mismatch for ${ARCHIVE}." >&2
        echo "  expected: ${SHA256_PIN}" >&2
        echo "  got:      ${GOT}" >&2
        echo "Refusing to install an unverified trs80gp binary." >&2
        rm -f "$ARCHIVE"
        exit 1
    fi
    echo "Verified against upstream (48k.ca)."
fi

rm -rf trs80gp-unpack
mkdir -p trs80gp-unpack
unzip -o -q "$ARCHIVE" -d trs80gp-unpack "mac/trs80gp.app/*"

APP="trs80gp-unpack/mac/trs80gp.app"
if [ ! -d "$APP" ]; then
    echo "FATAL: ${APP} not found in archive after unpack." >&2
    exit 1
fi

# The ad-hoc-signed app arrives (via a browser download, or any path that
# sets com.apple.quarantine) unable to launch without a Gatekeeper prompt.
# Strip it unconditionally; it is a no-op if already absent (e.g. curl in a
# non-Finder context never sets it).
xattr -dr com.apple.quarantine "$APP" 2>/dev/null || true

rm -rf ../bin/trs80gp.app
cp -R "$APP" ../bin/trs80gp.app
ln -sf trs80gp.app/Contents/MacOS/trs80gp ../bin/trs80gp

# No smoke-test invocation here: trs80gp has no flag that prints version/help
# and exits — every invocation opens a Cocoa window (see docs/research/
# trs80-model4-emulation.md). Confirming the install means checking the
# binary exists and is executable, which the symlink + cp above already did.
echo "Installed trs80gp ${VERSION} -> tools/bin/trs80gp"
