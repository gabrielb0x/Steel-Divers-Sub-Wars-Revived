# Reverse-engineering pipeline. Run ./setup.sh once, put the CIA in cia/, then `make`.
PY := .venv/bin/python
STAMPS := build/stamps

.PHONY: all extract elf analyze export scripts

all: export scripts

extract: extracted/manifest.json
elf: extracted/nsub.elf
analyze: $(STAMPS)/analyzed
export: $(STAMPS)/exported
scripts: $(STAMPS)/scripts

extracted/manifest.json:
	$(PY) tools/extract_cia.py

extracted/nsub.elf: extracted/manifest.json tools/code2elf.py tools/ctr.py
	$(PY) tools/code2elf.py

$(STAMPS)/analyzed: extracted/nsub.elf $(wildcard ghidra/scripts/*.java) ghidra/analyze.sh
	ghidra/analyze.sh
	@mkdir -p $(@D) && touch $@

$(STAMPS)/exported: $(STAMPS)/analyzed ghidra/export.sh ghidra/symbols.txt ghidra/types.h
	ghidra/export.sh
	@mkdir -p $(@D) && touch $@

# Pawn scripts: native parameter types (from the C++ pseudo-code), disassembly, pseudo-Pawn.
$(STAMPS)/scripts: $(STAMPS)/exported tools/amx.py tools/amxdec.py tools/native_types.py
	$(PY) tools/native_types.py
	$(PY) tools/amx.py
	$(PY) tools/amxdec.py
	@mkdir -p $(@D) && touch $@
