# Reverse-engineering pipeline. Run ./setup.sh once, put the CIA in cia/, then `make`.
PY := .venv/bin/python
STAMPS := build/stamps

.PHONY: all extract elf analyze export scripts data check-types

all: export scripts data

extract: extracted/manifest.json
elf: extracted/nsub.elf
analyze: $(STAMPS)/analyzed
export: $(STAMPS)/exported
scripts: $(STAMPS)/scripts
data: $(STAMPS)/data

extracted/manifest.json:
	$(PY) tools/extract_cia.py

extracted/nsub.elf: extracted/manifest.json tools/code2elf.py tools/ctr.py
	$(PY) tools/code2elf.py

$(STAMPS)/analyzed: extracted/nsub.elf $(wildcard ghidra/scripts/*.java) ghidra/analyze.sh
	ghidra/analyze.sh
	@mkdir -p $(@D) && touch $@

$(STAMPS)/exported: $(STAMPS)/analyzed ghidra/export.sh ghidra/symbols.txt ghidra/types.h
	$(MAKE) check-types
	ghidra/export.sh
	@mkdir -p $(@D) && touch $@

# Pawn scripts: native parameter types (from the C++ pseudo-code), disassembly, pseudo-Pawn.
$(STAMPS)/scripts: $(STAMPS)/exported tools/amx.py tools/amxdec.py tools/amxsym.py tools/native_types.py \
		$(wildcard decomp/pawn/*)
	$(PY) tools/native_types.py
	$(PY) tools/amx.py
	$(PY) tools/amxdec.py
	@mkdir -p $(@D) && touch $@

# Game data: BXML -> XML (extracted/xml/).
$(STAMPS)/data: extracted/manifest.json tools/bxml.py
	$(PY) tools/bxml.py
	@mkdir -p $(@D) && touch $@

# Struct layouts of ghidra/types.h against the offsets verified in the binary (32-bit).
check-types:
	gcc -m32 -fsyntax-only -Wall ghidra/types_check.c
