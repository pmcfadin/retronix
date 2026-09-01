ZMAC      ?= tools/bin/zmac
ALTAIRZ80 ?= tools/bin/altairz80
PYTHON    ?= python3

.PHONY: image image-m4 server test m0 tools clean

image: build/retronix.bin

build/retronix.bin: machine/bios.asm machine/protocol.inc
	@mkdir -p build
	$(ZMAC) --od build --oo cim,lst machine/bios.asm
	mv build/bios.cim build/retronix.bin

image-m4: build/retronix-m4.bin

build/retronix-m4.bin: machine/bios_m4.asm machine/protocol.inc
	@mkdir -p build
	$(ZMAC) --od build --oo cim,lst machine/bios_m4.asm
	mv build/bios_m4.cim build/retronix-m4.bin

server:
	$(PYTHON) -m compileall -q server

test:
	$(PYTHON) -m unittest discover -s server/tests -t . -v

m0: image
	$(PYTHON) harness/run_proof.py

play:
	harness/play.sh

tools:
	tools/build-tools.sh

clean:
	rm -rf build server/__pycache__ server/tests/__pycache__
