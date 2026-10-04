// Pre-script: pins the auto-analysis options so every import is reproducible.
//@category SteelDiver

import java.util.Map;

import ghidra.app.script.GhidraScript;

public class ConfigureAnalysis extends GhidraScript {

	@Override
	protected void run() throws Exception {
		Map<String, String> options = Map.of(
			// Infers parameters/returns (incl. VFP floats) for every function: much cleaner pseudo-code.
			"Decompiler Parameter ID", "true",
			// Data-pointer discovery is done by ScanCodePointers, with fewer false positives.
			"ARM Aggressive Instruction Finder", "false",
			"Embedded Media", "false",
			// Matches libc/OpenSSL prototypes by bare name, so every System::init or Stream::read
			// would get an EVP_PKEY_CTX* or ssize_t signature.
			"Apply Data Archives", "false",
			"Create Address Tables", "true",
			// Guesses wrong on conditional returns (moveq pc, lr): strlen, AMXLoader::getActor ... were
			// flagged non-returning, truncating every caller. Known ones (abort ...) are still handled.
			"Non-Returning Functions - Discovered", "false");
		for (Map.Entry<String, String> e : options.entrySet()) {
			try {
				setAnalysisOption(currentProgram, e.getKey(), e.getValue());
			}
			catch (Exception ex) {
				println("Could not set analysis option '" + e.getKey() + "': " + ex.getMessage());
			}
		}
	}
}
