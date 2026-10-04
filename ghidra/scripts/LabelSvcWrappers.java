// Names the CTR-SDK supervisor-call wrappers (svc #N; bx lr) after the 3DS SVC
// table, and comments every other SVC site. See https://www.3dbrew.org/wiki/SVC
//@category SteelDiver

import java.util.HashMap;
import java.util.Map;

import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.Function;
import ghidra.program.model.listing.Instruction;
import ghidra.program.model.listing.InstructionIterator;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.model.symbol.SourceType;

public class LabelSvcWrappers extends GhidraScript {

	private static final Map<Integer, String> SVCS = new HashMap<>();

	static {
		String[] names = {
			null, "ControlMemory", "QueryMemory", "ExitProcess", "GetProcessAffinityMask",
			"SetProcessAffinityMask", "GetProcessIdealProcessor", "SetProcessIdealProcessor", "CreateThread",
			"ExitThread", "SleepThread", "GetThreadPriority", "SetThreadPriority", "GetThreadAffinityMask",
			"SetThreadAffinityMask", "GetThreadIdealProcessor", "SetThreadIdealProcessor",
			"GetCurrentProcessorNumber", "Run", "CreateMutex", "ReleaseMutex", "CreateSemaphore",
			"ReleaseSemaphore", "CreateEvent", "SignalEvent", "ClearEvent", "CreateTimer", "SetTimer",
			"CancelTimer", "ClearTimer", "CreateMemoryBlock", "MapMemoryBlock", "UnmapMemoryBlock",
			"CreateAddressArbiter", "ArbitrateAddress", "CloseHandle", "WaitSynchronization1",
			"WaitSynchronizationN", "SignalAndWait", "DuplicateHandle", "GetSystemTick", "GetHandleInfo",
			"GetSystemInfo", "GetProcessInfo", "GetThreadInfo", "ConnectToPort", "SendSyncRequest1",
			"SendSyncRequest2", "SendSyncRequest3", "SendSyncRequest4", "SendSyncRequest", "OpenProcess",
			"OpenThread", "GetProcessId", "GetProcessIdOfThread", "GetThreadId", "GetResourceLimit",
			"GetResourceLimitLimitValues", "GetResourceLimitCurrentValues", "GetThreadContext", "Break",
			"OutputDebugString", "ControlPerformanceCounter",
		};
		for (int i = 1; i < names.length; i++) {
			SVCS.put(i, names[i]);
		}
		SVCS.put(0x47, "CreatePort");
		SVCS.put(0x48, "CreateSessionToPort");
		SVCS.put(0x49, "CreateSession");
		SVCS.put(0x4A, "AcceptSession");
		SVCS.put(0x4F, "ReplyAndReceive");
		SVCS.put(0x50, "BindInterrupt");
		SVCS.put(0x51, "UnbindInterrupt");
		SVCS.put(0x52, "InvalidateProcessDataCache");
		SVCS.put(0x53, "StoreProcessDataCache");
		SVCS.put(0x54, "FlushProcessDataCache");
		SVCS.put(0x55, "StartInterProcessDma");
		SVCS.put(0x56, "StopDma");
		SVCS.put(0x57, "GetDmaState");
		SVCS.put(0x58, "RestartDma");
		SVCS.put(0x59, "SetGpuProt");
		SVCS.put(0x5A, "SetWifiEnabled");
		SVCS.put(0x7B, "Backdoor");
		SVCS.put(0x7C, "KernelSetState");
		SVCS.put(0xFF, "StopPoint");
	}

	@Override
	protected void run() throws Exception {
		int wrappers = 0;
		int sites = 0;
		InstructionIterator it = currentProgram.getListing().getInstructions(true);
		while (it.hasNext() && !monitor.isCancelled()) {
			Instruction insn = it.next();
			String mnemonic = insn.getMnemonicString().toLowerCase();
			if (!mnemonic.startsWith("svc") && !mnemonic.startsWith("swi")) {
				continue;
			}
			Object[] ops = insn.getOpObjects(0);
			if (ops.length == 0 || !(ops[0] instanceof Scalar)) {
				continue;
			}
			int id = (int) ((Scalar) ops[0]).getUnsignedValue();
			String name = SVCS.getOrDefault(id, String.format("Unknown%02X", id));
			sites++;
			setEOLComment(insn.getAddress(), String.format("svc 0x%02X: %s", id, name));

			Function f = getFunctionContaining(insn.getAddress());
			if (f != null && f.getName().startsWith("FUN_") && f.getBody().getNumAddresses() <= 0x30) {
				f.setName("svc" + name, SourceType.ANALYSIS);
				wrappers++;
			}
		}
		println(String.format("SVC sites: %d, wrappers named: %d", sites, wrappers));
	}
}
