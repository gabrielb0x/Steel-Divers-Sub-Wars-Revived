// Pre-script: applies the linker symbol map shipped in the RomFS (romfs:/map).
//
// Each line is "<address> <size> <demangled name> <object>", e.g.
//   0x00101118 184 amxSysInit amxsys.o
//   0x00100f84 316 nninitStartUp system.o
//   0x001010c0 88 $Sub$$_ZN2nn6applet3CTR6detail10InitializeEj libnn_applet.fast.a(applet_API.o)
//
// For every entry the script creates the namespace hierarchy, a primary label,
// a function, a "lib:"/"obj:" tag and a plate comment naming the object file.
// Usage: -preScript ImportSymbolMap.java <path to map>
//@category SteelDiver

import java.io.BufferedReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Namespace;
import ghidra.program.model.symbol.SourceType;
import ghidra.program.model.symbol.SymbolTable;
import ghidra.program.model.symbol.SymbolUtilities;

public class ImportSymbolMap extends GhidraScript {

	private static final Pattern LINE = Pattern.compile("^0x([0-9a-fA-F]+)\\s+(\\d+)\\s+(.+)\\s+(\\S+)$");
	private static final Pattern LIB_MEMBER = Pattern.compile("^(\\S+?)\\.(?:fast\\.)?[al]\\((\\S+)\\)$");

	@Override
	protected void run() throws Exception {
		String[] args = getScriptArgs();
		if (args.length < 1) {
			throw new IllegalArgumentException("usage: ImportSymbolMap.java <path to romfs map>");
		}
		SymbolTable symbols = currentProgram.getSymbolTable();
		int functions = 0;
		int failed = 0;

		try (BufferedReader reader = Files.newBufferedReader(Path.of(args[0]), StandardCharsets.ISO_8859_1)) {
			String line;
			while ((line = reader.readLine()) != null && !monitor.isCancelled()) {
				Matcher m = LINE.matcher(line.strip());
				if (!m.matches()) {
					continue;
				}
				Address addr = toAddr(Long.parseLong(m.group(1), 16));
				String object = m.group(4);
				List<String> parts = splitQualifiedName(m.group(3));
				try {
					Namespace ns = currentProgram.getGlobalNamespace();
					for (int i = 0; i < parts.size() - 1; i++) {
						String part = clean(parts.get(i));
						Namespace child = symbols.getNamespace(part, ns);
						ns = child != null ? child : symbols.createNameSpace(ns, part, SourceType.IMPORTED);
					}
					String name = clean(parts.get(parts.size() - 1));
					symbols.createLabel(addr, name, ns, SourceType.IMPORTED).setPrimary();
					symbols.addExternalEntryPoint(addr);

					if (getInstructionAt(addr) == null) {
						new DisassembleCommand(addr, null, true).applyTo(currentProgram, monitor);
					}
					Function f = getFunctionAt(addr);
					if (f == null) {
						f = createFunction(addr, null);
					}
					if (f == null) {
						failed++;
						continue;
					}
					Matcher lib = LIB_MEMBER.matcher(object);
					f.addTag(lib.matches() ? "lib:" + lib.group(1) : "game");
					setPlateComment(addr,
						m.group(3) + "\nobject: " + object + "\nsize: " + m.group(2) + " bytes (linker map)");
					functions++;
				}
				catch (Exception e) {
					failed++;
					println("Failed at " + addr + " (" + m.group(3) + "): " + e.getMessage());
				}
			}
		}
		println(String.format("Symbol map applied: %d functions, %d failures", functions, failed));
	}

	/** Splits "a::b<c::d>::e" on top-level "::" (outside template/parameter brackets). */
	static List<String> splitQualifiedName(String name) {
		List<String> parts = new ArrayList<>();
		int depth = 0;
		int start = 0;
		for (int i = 0; i < name.length(); i++) {
			char c = name.charAt(i);
			if (c == '<' || c == '(') {
				depth++;
			}
			else if ((c == '>' || c == ')') && depth > 0) {
				depth--;
			}
			else if (c == ':' && depth == 0 && i + 1 < name.length() && name.charAt(i + 1) == ':') {
				parts.add(name.substring(start, i));
				start = i + 2;
				i++;
			}
		}
		parts.add(name.substring(start));
		return parts;
	}

	private static String clean(String part) {
		return SymbolUtilities.replaceInvalidChars(part.strip(), true);
	}
}
