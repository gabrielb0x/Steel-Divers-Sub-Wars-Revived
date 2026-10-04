// Types the Pawn native functions. Follows every call to
// amx_Register(amx, table, -1), labels the AMX_NATIVE_INFO table (declared
// packed, so it may be unaligned) and gives each native the AMX_NATIVE
// prototype: cell f(AMX *amx, cell *params). Run after ApplySymbols, which
// parses the AMX types from ghidra/types.h.
//@category SteelDiver

import java.util.ArrayList;
import java.util.List;

import ghidra.app.cmd.function.ApplyFunctionSignatureCmd;
import ghidra.app.cmd.function.FunctionRenameOption;
import ghidra.app.script.GhidraScript;
import ghidra.app.services.DataTypeManagerService;
import ghidra.app.util.cparser.C.CParserUtils;
import ghidra.program.model.address.Address;
import ghidra.program.model.data.ArrayDataType;
import ghidra.program.model.data.DataType;
import ghidra.program.model.data.FunctionDefinitionDataType;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.symbol.Reference;
import ghidra.program.model.symbol.SourceType;

public class TypeAmxNatives extends GhidraScript {

	@Override
	protected void run() throws Exception {
		List<Function> register = getGlobalFunctions("amx_Register");
		if (register.isEmpty()) {
			throw new IllegalStateException("amx_Register not found");
		}
		List<DataType> found = new ArrayList<>();
		currentProgram.getDataTypeManager().findDataTypes("AMX_NATIVE_INFO", found);
		if (found.isEmpty()) {
			throw new IllegalStateException("AMX_NATIVE_INFO missing: run ApplySymbols (types.h) first");
		}
		DataType info = found.get(0);
		FunctionDefinitionDataType nativeSig = CParserUtils.parseSignature((DataTypeManagerService) null,
			currentProgram, "cell f(AMX * amx, cell * params)", false);

		int tables = 0;
		int natives = 0;
		for (Reference ref : getReferencesTo(register.get(0).getEntryPoint())) {
			Address table = tableArgument(ref.getFromAddress());
			if (table == null) {
				continue;
			}
			int count = 0;
			for (Address entry = table; getInt(entry) != 0 || getInt(entry.add(4)) != 0; entry = entry.add(8)) {
				Address func = toAddr(getInt(entry.add(4)) & 0xFFFFFFFFL);
				Function f = getFunctionAt(func);
				if (f == null) {
					f = createFunction(func, null);
				}
				if (f != null) {
					new ApplyFunctionSignatureCmd(func, nativeSig, SourceType.ANALYSIS, true,
						FunctionRenameOption.NO_CHANGE).applyTo(currentProgram, monitor);
					natives++;
				}
				count++;
			}
			Function owner = getFunctionContaining(ref.getFromAddress());
			String label = "natives_" + (owner != null ? owner.getName().replace("amx_", "").replace("Init", "") : table);
			clearListing(table, table.add(8L * (count + 1) - 1));
			createData(table, new ArrayDataType(info, count + 1, info.getLength()));
			createLabel(table, label, true, SourceType.ANALYSIS);
			tables++;
		}
		println(String.format("AMX natives typed: %d in %d tables", natives, tables));
	}

	/** The `ldr r1, =table` feeding a call to amx_Register, within the preceding instructions. */
	private Address tableArgument(Address call) throws Exception {
		Instruction insn = getInstructionAt(call);
		for (int k = 0; k < 12 && insn != null; k++) {
			insn = insn.getPrevious();
			if (insn == null || !insn.getMnemonicString().equalsIgnoreCase("ldr")) {
				continue;
			}
			if (insn.getRegister(0) == null || !insn.getRegister(0).getName().equals("r1")) {
				continue;
			}
			Reference pool = insn.getPrimaryReference(1);
			if (pool == null) {
				return null;
			}
			return toAddr(getInt(pool.getToAddress()) & 0xFFFFFFFFL);
		}
		return null;
	}
}
