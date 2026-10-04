#!/usr/bin/env bash
# Imports extracted/nsub.elf into ghidra/project/, applies the linker symbol
# map shipped in the RomFS, runs the auto-analysis, then the SteelDiver
# scripts (SVC labels, vtable-only functions, ghidra/symbols.txt + types.h).
#
# The project is recreated from scratch: the previous one is kept in
# ghidra/project.bak/. Knowledge must live in symbols.txt/types.h, not in the
# Ghidra database.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$ROOT/local.env" ] && source "$ROOT/local.env"
: "${GHIDRA_INSTALL_DIR:?GHIDRA_INSTALL_DIR is not set (run ./setup.sh)}"
export GHIDRA_HEADLESS_MAXMEM="${GHIDRA_HEADLESS_MAXMEM:-3G}"

if [ -d "$ROOT/ghidra/project" ]; then
	rm -rf -- "${ROOT:?}/ghidra/project.bak"
	mv "$ROOT/ghidra/project" "$ROOT/ghidra/project.bak"
fi
mkdir -p "$ROOT/ghidra/project" "$ROOT/build/logs"
"$GHIDRA_INSTALL_DIR/support/analyzeHeadless" "$ROOT/ghidra/project" SteelDiver \
	-import "$ROOT/extracted/nsub.elf" \
	-processor ARM:LE:32:v6 \
	-scriptPath "$ROOT/ghidra/scripts" \
	-preScript ConfigureAnalysis.java \
	-preScript ImportSymbolMap.java "$ROOT/extracted/romfs/map" \
	-postScript LabelSvcWrappers.java \
	-postScript ScanCodePointers.java \
	-postScript ApplySymbols.java "$ROOT/ghidra/types.h" "$ROOT/ghidra/symbols.txt" \
	-postScript TypeAmxNatives.java \
	-log "$ROOT/build/logs/ghidra-analyze.log" \
	-scriptlog "$ROOT/build/logs/ghidra-scripts.log"
