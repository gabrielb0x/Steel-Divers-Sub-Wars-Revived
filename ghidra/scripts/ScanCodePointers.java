// Finds functions only reachable through pointers stored in .rodata/.data
// (C++ vtables, callback tables, AMX native tables) and defines them.
//
// The binary has no relocations and the linker map does not list every function
// (static helpers, runtime library), so the auto-analysis misses code that is
// only reachable through vtables. A pointer target is accepted when it lies in
// .text outside any known function body and
// either sits in a run of >= 3 consecutive code pointers (vtable-like) or
// starts with a classic ARM prologue (stmdb sp!, {..., lr}).
//@category SteelDiver

import java.math.BigInteger;

import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.lang.Register;
import ghidra.program.model.listing.Listing;
import ghidra.program.model.mem.Memory;
import ghidra.program.model.mem.MemoryBlock;

public class ScanCodePointers extends GhidraScript {

	private static final int MIN_RUN = 3;

	private Memory mem;
	private MemoryBlock text;

	@Override
	protected void run() throws Exception {
		mem = currentProgram.getMemory();
		text = mem.getBlock(".text");
		int created = 0;
		for (int pass = 1; pass <= 3; pass++) {
			int n = 0;
			for (String blockName : new String[] { ".rodata", ".data", ".text" }) {
				n += scanBlock(mem.getBlock(blockName));
			}
			println(String.format("pass %d: %d new functions", pass, n));
			created += n;
			if (n == 0) {
				break;
			}
			analyzeChanges(currentProgram);
		}
		println("Total functions created from data pointers: " + created);
	}

	private boolean isCodePointer(long value) {
		long target = value & ~1L;
		if (target < text.getStart().getOffset() || target > text.getEnd().getOffset()) {
			return false;
		}
		// ARM code is 4-byte aligned; Thumb pointers have bit 0 set.
		return (value & 1) == 1 || (value & 3) == 0;
	}

	private int scanBlock(MemoryBlock block) throws Exception {
		if (block == null || !block.isInitialized()) {
			return 0;
		}
		Listing listing = currentProgram.getListing();
		Register tmode = currentProgram.getRegister("TMode");
		long start = (block.getStart().getOffset() + 3) & ~3L;
		long end = block.getEnd().getOffset();
		boolean inText = block == text;
		int created = 0;

		long addr = start;
		while (addr + 4 <= end && !monitor.isCancelled()) {
			// Measure the run of consecutive code pointers starting here.
			int run = 0;
			while (addr + 4L * (run + 1) <= end && isCodePointer(readWord(addr + 4L * run))) {
				run++;
			}
			if (run == 0) {
				addr += 4;
				continue;
			}
			for (int i = 0; i < run; i++) {
				Address where = toAddr(addr + 4L * i);
				// Inside .text only consider literal-pool words, never real instructions.
				if (inText && listing.getInstructionContaining(where) != null) {
					continue;
				}
				long value = readWord(addr + 4L * i);
				Address target = toAddr(value & ~1L);
				boolean thumb = (value & 1) == 1;
				// Pointers into an existing body are switch-table/label targets, not functions.
				if (getFunctionContaining(target) != null) {
					continue;
				}
				boolean accept = run >= MIN_RUN || (!thumb && looksLikeArmPrologue(target));
				if (!accept || listing.getInstructionContaining(target) != null && listing.getInstructionAt(target) == null) {
					continue;
				}
				if (listing.getInstructionAt(target) == null) {
					if (listing.getDefinedDataContaining(target) != null) {
						continue;
					}
					if (tmode != null) {
						currentProgram.getProgramContext().setValue(tmode, target, target,
							thumb ? BigInteger.ONE : BigInteger.ZERO);
					}
					DisassembleCommand cmd = new DisassembleCommand(target, null, true);
					if (!cmd.applyTo(currentProgram, monitor) || listing.getInstructionAt(target) == null) {
						continue;
					}
				}
				if (createFunction(target, null) != null) {
					created++;
				}
			}
			addr += 4L * run;
		}
		return created;
	}

	private long readWord(long offset) throws Exception {
		return mem.getInt(toAddr(offset)) & 0xFFFFFFFFL;
	}

	private boolean looksLikeArmPrologue(Address target) {
		try {
			long insn = mem.getInt(target) & 0xFFFFFFFFL;
			return (insn & 0xFFFF4000L) == 0xE92D4000L;
		}
		catch (Exception e) {
			return false;
		}
	}
}
