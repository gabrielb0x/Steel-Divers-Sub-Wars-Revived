# Reverse-engineering pipeline. Run ./setup.sh once, put the CIA in cia/, then `make`.
PY := .venv/bin/python
STAMPS := build/stamps

.PHONY: all extract elf analyze export scripts data check-types azahar pawncc bots

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

# The game for the Azahar emulator: CIA without the encrypted manual, and CXI (build/azahar/).
azahar: extracted/manifest.json
	$(PY) tools/azahar.py prepare

# Pawn 3.3 compiler (CompuPhase, Apache 2.0), a tool of the build only: build/pawncc, for tools/pawn2pasm.py.
# _I32_MAX/_I32_MIN: without them a 64-bit build sets cellmax/cellmin from LONG_MAX/LONG_MIN (cellmin = 0).
PAWN_SRC := build/ref/compuphase-pawn
PAWN_33 := build/pawn33
pawncc: build/pawncc
build/pawncc:
	test -d $(PAWN_SRC) || git clone https://github.com/compuphase/pawn $(PAWN_SRC)
	test -d $(PAWN_33) || git -C $(PAWN_SRC) worktree add --detach $(CURDIR)/$(PAWN_33) 6d82fa4
	cd $(PAWN_33)/compiler && gcc -O1 -w -DLINUX -DHAVE_STDINT_H -D_I32_MAX=2147483647 '-D_I32_MIN=(-2147483647-1)' \
		-I. -I../amx -I../linux -o $(CURDIR)/$@ sc1.c sc2.c sc3.c sc4.c sc5.c sc6.c sc7.c scexpand.c sci18n.c \
		sclist.c scmemfil.c scstate.c scvars.c lstring.c memfile.c ../linux/binreloc.c -lm

# The bots of the online battles, written in Pawn (mods/en-ligne/src) -> mods/en-ligne/*.pasm (committed);
# tools/botsim.py runs them in a sandbox. The same for the update v5200 (*-v5200.pasm): the Pawn sources compiled
# for its scripts, the hand-written .pasm translated by tools/amxport.py (addresses it cannot pair: v5200.toml).
BOTS_SRC := $(wildcard mods/en-ligne/src/*.p)
BOTS_PASM := bots_salon:mode_lobby bots_bataille:mode_periscope bots_hud:hud bots_joueur:pscope_player \
	anti_triche_joueur:pscope_player anti_triche_tir:periscope_move
bots: build/pawncc
	python3 tools/pawn2pasm.py $(BOTS_SRC) mods/premium/src/couleurs.p
	python3 tools/pawn2pasm.py --version v5200 $(BOTS_SRC) mods/premium/src/couleurs.p
	for p in $(BOTS_PASM); do python3 tools/amxport.py $${p#*:} --pasm mods/en-ligne/$${p%%:*}.pasm \
		mods/en-ligne/$${p%%:*}-v5200.pasm --overrides mods/en-ligne/v5200.toml || exit 1; done
