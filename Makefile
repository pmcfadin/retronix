ZMAC      ?= tools/bin/zmac
ALTAIRZ80 ?= tools/bin/altairz80
PYTHON    ?= python3

.PHONY: image server test m0 tools clean

image: build/retronix.bin

build/retronix.bin: machine/bios.asm machine/protocol.inc
	@mkdir -p build
	$(ZMAC) --od build --oo cim,lst machine/bios.asm
	mv build/bios.cim build/retronix.bin

server:
	$(PYTHON) -m compileall -q server

test:
	$(PYTHON) -m unittest discover -s server/tests -t . -v

m0: image
	$(PYTHON) harness/run_m0.py

tools:
	tools/build-tools.sh

clean:
	rm -rf build server/__pycache__ server/tests/__pycache__
