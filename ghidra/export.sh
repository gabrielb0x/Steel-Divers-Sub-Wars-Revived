#!/usr/bin/env bash
# Re-applies ghidra/symbols.txt + types.h to the analysed program (in memory,
# the database is opened read-only) and decompiles everything into the
# pseudo-source tree decomp/raw/ (not versioned). Edit symbols.txt, re-run.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$ROOT/local.env" ] && source "$ROOT/local.env"
: "${GHIDRA_INSTALL_DIR:?GHIDRA_INSTALL_DIR is not set (run ./setup.sh)}"
export GHIDRA_HEADLESS_MAXMEM="${GHIDRA_HEADLESS_MAXMEM:-3G}"

# Start from an empty tree so functions that moved files leave no stale copies behind.
rm -rf -- "${ROOT:?}/decomp/raw"
mkdir -p "$ROOT/decomp/raw" "$ROOT/build/logs"
"$GHIDRA_INSTALL_DIR/support/analyzeHeadless" "$ROOT/ghidra/project" SteelDiver \
	-process nsub.elf -noanalysis -readOnly \
	-scriptPath "$ROOT/ghidra/scripts" \
	-postScript ApplySymbols.java "$ROOT/ghidra/types.h" "$ROOT/ghidra/symbols.txt" \
	-postScript TypeAmxNatives.java \
	-postScript ExportPseudoSource.java "$ROOT/decomp/raw" "$ROOT/extracted/romfs/map" \
	-log "$ROOT/build/logs/ghidra-export.log" \
	-scriptlog "$ROOT/build/logs/ghidra-export-scripts.log"
