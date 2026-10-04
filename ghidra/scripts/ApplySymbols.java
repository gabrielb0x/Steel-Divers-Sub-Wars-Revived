// Applies the hand-maintained knowledge kept in git on top of the linker map:
// C types from ghidra/types.h, then names and prototypes from ghidra/symbols.txt.
// The Ghidra database is disposable; these two files are the source of truth.
//
// symbols.txt, one function per line:   <address> <qualified name> [: <C prototype>]
//   0x00254000 operator_new : void * f(u32 size)
//   0x00103758 System::getRunningTimeInSeconds : float f(void)
// The prototype's own function name is ignored; methods take an explicit `this`.
// Usage: -postScript ApplySymbols.java <types.h> <symbols.txt>
//@category SteelDiver

import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;

import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.cmd.function.ApplyFunctionSignatureCmd;
import ghidra.app.cmd.function.FunctionRenameOption;
import ghidra.app.script.GhidraScript;
import ghidra.app.services.DataTypeManagerService;
import ghidra.app.util.cparser.C.CParser;
import ghidra.app.util.cparser.C.CParserUtils;
import ghidra.program.model.address.Address;
import ghidra.program.model.data.FunctionDefinitionDataType;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Namespace;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.symbol.SymbolTable;
import ghidra.program.model.symbol.SymbolUtilities;

public class ApplySymbols extends GhidraScript {

	@Override
	protected void run() throws Exception {
		String[] args = getScriptArgs();
		if (args.length < 2) {
			throw new IllegalArgumentException("usage: ApplySymbols.java <types.h> <symbols.txt>");
		}
		Path types = Path.of(args[0]);
		if (Files.exists(types)) {
			CParser parser = new CParser(currentProgram.getDataTypeManager(), true, null);
			parser.setParseFileName(types.getFileName().toString());
			try (InputStream in = Files.newInputStream(types)) {
				parser.parse(in);
			}
			if (!parser.didParseSucceed()) {
				throw new IllegalStateException("types.h: " + parser.getParseMessages());
			}
		}

		int applied = 0;
		int errors = 0;
		List<String> lines = Files.readAllLines(Path.of(args[1]), StandardCharsets.UTF_8);
		for (int n = 0; n < lines.size(); n++) {
			String line = lines.get(n).strip();
			if (line.isEmpty() || line.startsWith("#")) {
				continue;
			}
			try {
				apply(line);
				applied++;
			}
			catch (Exception e) {
				errors++;
				println(String.format("symbols.txt:%d: %s (%s)", n + 1, e.getMessage(), line));
			}
		}
		println(String.format("symbols.txt: %d entries applied, %d errors", applied, errors));
	}

	private void apply(String line) throws Exception {
		int colon = line.indexOf(" : ");
		String prototype = colon >= 0 ? line.substring(colon + 3).strip() : null;
		String[] head = (colon >= 0 ? line.substring(0, colon) : line).strip().split("\\s+");
		if (head.length != 2) {
			throw new IllegalArgumentException("expected '<address> <name> [: <prototype>]'");
		}
		Address addr = toAddr(Long.decode(head[0]));

		if (getInstructionAt(addr) == null) {
			new DisassembleCommand(addr, null, true).applyTo(currentProgram, monitor);
		}
		Function f = getFunctionAt(addr);
		if (f == null) {
			f = createFunction(addr, null);
		}
		if (f == null) {
			throw new IllegalStateException("cannot create a function at " + addr);
		}

		List<String> parts = ImportSymbolMap.splitQualifiedName(head[1]);
		SymbolTable symbols = currentProgram.getSymbolTable();
		Namespace ns = currentProgram.getGlobalNamespace();
		for (String part : parts.subList(0, parts.size() - 1)) {
			part = SymbolUtilities.replaceInvalidChars(part, true);
			Namespace child = symbols.getNamespace(part, ns);
			ns = child != null ? child : symbols.createNameSpace(ns, part, SourceType.USER_DEFINED);
		}
		f.setParentNamespace(ns);
		f.setName(SymbolUtilities.replaceInvalidChars(parts.get(parts.size() - 1), true), SourceType.USER_DEFINED);

		if (prototype != null) {
			FunctionDefinitionDataType def =
				CParserUtils.parseSignature((DataTypeManagerService) null, currentProgram, prototype, false);
			ApplyFunctionSignatureCmd cmd = new ApplyFunctionSignatureCmd(addr, def, SourceType.USER_DEFINED,
				true, FunctionRenameOption.NO_CHANGE);
			if (!cmd.applyTo(currentProgram, monitor)) {
				throw new IllegalStateException(cmd.getStatusMsg());
			}
		}
	}
}
