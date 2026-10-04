// Decompiles every function and writes the pseudo-source tree, one file per
// original object file from the linker map:
//
//   <out>/source/amx/amxsys.cpp           game code (paths from the __FILE__ strings)
//   <out>/lib/libnw_gfx/gfx_Model.cpp      SDK / middleware, grouped by library
//   <out>/unmapped/0x0033a874.cpp          functions absent from the map
//   <out>/functions.csv                    address, sizes, name, object, file
//
// Usage: -postScript ExportPseudoSource.java <out dir> <path to romfs map>
//@category SteelDiver

import java.io.BufferedReader;
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileOptions;
import ghidra.app.decompiler.DecompileResults;
import ghidra.app.decompiler.parallel.DecompilerCallback;
import ghidra.app.decompiler.parallel.ParallelDecompiler;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.mem.MemoryBlock;
import ghidra.util.task.TaskMonitor;

public class ExportPseudoSource extends GhidraScript {

	private static final Pattern MAP_LINE = Pattern.compile("^0x([0-9a-fA-F]+)\\s+(\\d+)\\s+(.+)\\s+(\\S+)$");
	private static final Pattern LIB_MEMBER = Pattern.compile("^(\\S+?)\\.(?:fast\\.)?[al]\\((\\S+)\\)$");
	private static final Pattern SOURCE_PATH = Pattern.compile("source[/\\\\][A-Za-z0-9_/\\\\.]+\\.(?:cpp|c)");
	private static final int TIMEOUT_SECONDS = 120;

	private record MapEntry(long address, int size, String name, String object) {}

	private record Decompiled(long address, String code) {}

	@Override
	protected void run() throws Exception {
		String[] args = getScriptArgs();
		if (args.length < 2) {
			throw new IllegalArgumentException("usage: ExportPseudoSource.java <out dir> <romfs map>");
		}
		Path out = Path.of(args[0]);
		TreeMap<Long, MapEntry> map = readMap(Path.of(args[1]));
		Map<String, String> sourcePaths = findSourcePaths();
		println(String.format("%d map entries, %d source paths found in the binary", map.size(), sourcePaths.size()));

		List<Function> functions = new ArrayList<>();
		currentProgram.getFunctionManager().getFunctions(true).forEach(functions::add);

		// Assign every function to an output file.
		Map<Long, String> fileOf = new HashMap<>();
		Map<Long, String> objectOf = new HashMap<>();
		for (Function f : functions) {
			long addr = f.getEntryPoint().getOffset();
			String object = objectFor(map, addr);
			objectOf.put(addr, object);
			fileOf.put(addr, object != null ? fileFor(object, sourcePaths)
					: String.format("unmapped/0x%08x.cpp", addr & ~0xFFFFL));
		}

		DecompilerCallback<Decompiled> callback =
			new DecompilerCallback<>(currentProgram, ExportPseudoSource::configure) {
				@Override
				public Decompiled process(DecompileResults results, TaskMonitor m) {
					long addr = results.getFunction().getEntryPoint().getOffset();
					if (results.getDecompiledFunction() == null) {
						return new Decompiled(addr, "/* decompilation failed: " + results.getErrorMessage() + " */\n");
					}
					return new Decompiled(addr, results.getDecompiledFunction().getC());
				}
			};
		callback.setTimeout(TIMEOUT_SECONDS);
		monitor.setMessage("Decompiling " + functions.size() + " functions");
		List<Decompiled> results;
		try {
			results = ParallelDecompiler.decompileFunctions(callback, functions, monitor);
		}
		finally {
			callback.dispose();
		}

		TreeMap<String, TreeMap<Long, String>> files = new TreeMap<>();
		for (Decompiled d : results) {
			if (d != null) {
				files.computeIfAbsent(fileOf.get(d.address()), k -> new TreeMap<>()).put(d.address(), d.code());
			}
		}

		for (Map.Entry<String, TreeMap<Long, String>> file : files.entrySet()) {
			Path path = out.resolve(file.getKey());
			Files.createDirectories(path.getParent());
			try (PrintWriter w = new PrintWriter(Files.newBufferedWriter(path, StandardCharsets.UTF_8))) {
				long first = file.getValue().firstKey();
				w.println("// Steel Diver: Sub Wars (CTR-N-JNUP) - Ghidra pseudo-code, AUTO-GENERATED.");
				w.println("// Object: " + (objectOf.get(first) != null ? objectOf.get(first) : "(not in linker map)"));
				w.println("// Regenerate with ghidra/export.sh; curated code lives in decomp/src/.");
				for (Map.Entry<Long, String> fn : file.getValue().entrySet()) {
					MapEntry e = map.get(fn.getKey());
					w.println();
					w.printf("// %08X%s%n", fn.getKey(), e != null ? String.format(" size %d: %s", e.size(), e.name()) : "");
					w.print(fn.getValue().strip() + "\n");
				}
			}
		}

		try (PrintWriter w = new PrintWriter(Files.newBufferedWriter(out.resolve("functions.csv"), StandardCharsets.UTF_8))) {
			w.println("address,map_size,ghidra_size,name,object,file");
			for (Function f : functions) {
				long addr = f.getEntryPoint().getOffset();
				MapEntry e = map.get(addr);
				w.printf("0x%08X,%s,%d,\"%s\",%s,%s%n", addr, e != null ? e.size() : "",
					f.getBody().getNumAddresses(), e != null ? e.name() : f.getName(true),
					objectOf.get(addr) != null ? objectOf.get(addr) : "", fileOf.get(addr));
			}
		}
		println(String.format("Exported %d functions into %d files under %s", results.size(), files.size(), out));
	}

	private static void configure(DecompInterface decompiler) {
		DecompileOptions options = new DecompileOptions();
		decompiler.setOptions(options);
		decompiler.toggleCCode(true);
		decompiler.toggleSyntaxTree(false);
		decompiler.setSimplificationStyle("decompile");
	}

	private TreeMap<Long, MapEntry> readMap(Path path) throws Exception {
		TreeMap<Long, MapEntry> map = new TreeMap<>();
		try (BufferedReader reader = Files.newBufferedReader(path, StandardCharsets.ISO_8859_1)) {
			String line;
			while ((line = reader.readLine()) != null) {
				Matcher m = MAP_LINE.matcher(line.strip());
				if (m.matches()) {
					long addr = Long.parseLong(m.group(1), 16);
					map.put(addr, new MapEntry(addr, Integer.parseInt(m.group(2)), m.group(3), m.group(4)));
				}
			}
		}
		return map;
	}

	/**
	 * Object file a function belongs to: its own map entry, or, for functions the
	 * map does not list (static helpers), the object shared by both neighbours.
	 */
	private static String objectFor(TreeMap<Long, MapEntry> map, long addr) {
		MapEntry exact = map.get(addr);
		if (exact != null) {
			return exact.object();
		}
		Map.Entry<Long, MapEntry> before = map.lowerEntry(addr);
		Map.Entry<Long, MapEntry> after = map.higherEntry(addr);
		if (before != null && after != null && before.getValue().object().equals(after.getValue().object())) {
			return before.getValue().object();
		}
		return null;
	}

	private static String fileFor(String object, Map<String, String> sourcePaths) {
		Matcher lib = LIB_MEMBER.matcher(object);
		if (lib.matches()) {
			String member = lib.group(2).replaceAll("\\.(o|obj)$", "");
			if (!member.matches(".*\\.(c|cpp)$")) {
				member += ".cpp";
			}
			return "lib/" + lib.group(1) + "/" + member;
		}
		String base = object.replaceAll("\\.o$", "");
		if (base.endsWith(".fast")) {
			// SDK objects linked directly (crt0.fast.o).
			return "lib/sdk/" + base.replaceAll("\\.fast$", "") + ".cpp";
		}
		String known = sourcePaths.get(base.toLowerCase());
		if (known != null) {
			return known;
		}
		// Not confirmed by a __FILE__ string: only the Pawn natives are obvious enough to file.
		return (base.startsWith("amx") ? "source/amx/" : "source/") + base + ".cpp";
	}

	/** Collects the "source/dir/file.cpp" strings (__FILE__ of the game's asserts/logs). */
	private Map<String, String> findSourcePaths() throws Exception {
		Map<String, String> paths = new HashMap<>();
		for (MemoryBlock block : currentProgram.getMemory().getBlocks()) {
			// armcc emits most string literals right after the code, inside .text.
			if (!block.isInitialized()) {
				continue;
			}
			byte[] bytes = new byte[(int) block.getSize()];
			block.getBytes(block.getStart(), bytes);
			Matcher m = SOURCE_PATH.matcher(new String(bytes, StandardCharsets.ISO_8859_1));
			while (m.find()) {
				String path = m.group().replace('\\', '/');
				String base = path.substring(path.lastIndexOf('/') + 1).replaceAll("\\.(cpp|c)$", "");
				paths.put(base.toLowerCase(), path);
			}
		}
		return paths;
	}
}
