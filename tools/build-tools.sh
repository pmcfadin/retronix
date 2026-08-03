#!/bin/sh
# Build the M0 toolchain from source into tools/bin/.
# zmac:      http://48k.ca/zmac.html (18oct2022)
# altairz80: https://github.com/open-simh/simh (built NOVIDEO=1 — the sim is
#            headless; SDL video would add a runtime dependency and, on macOS,
#            a link failure from a missing -lz)
set -e
cd "$(dirname "$0")"
mkdir -p bin work
cd work

if [ ! -x ../bin/zmac ]; then
    curl -sSL -o zmac.zip http://48k.ca/zmac.zip
    unzip -o -q zmac.zip -d zmac
    (cd zmac/src && make CC=cc CXX=c++)
    cp zmac/src/zmac ../bin/zmac
fi

if [ ! -x ../bin/altairz80 ]; then
    curl -sSL -o simh.tar.gz https://github.com/open-simh/simh/archive/refs/heads/master.tar.gz
    tar xzf simh.tar.gz
    (cd simh-master && make altairz80 NOVIDEO=1)
    cp simh-master/BIN/altairz80 ../bin/altairz80
fi

../bin/zmac --version
echo "show version" | ../bin/altairz80 | head -1
