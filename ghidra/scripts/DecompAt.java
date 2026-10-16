// Decompile functions at the given addresses, creating them first if analysis missed them
// (changes are not saved with -readOnly).  args: outfile addr1 addr2 ...
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.app.cmd.disassemble.DisassembleCommand;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import java.io.*;

public class DecompAt extends GhidraScript {
    public void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter out = new PrintWriter(new FileWriter(a[0]));
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        for (int i = 1; i < a.length; i++) {
            Address t = toAddr(a[i]);
            Function f = getFunctionAt(t);
            if (f == null) {
                new DisassembleCommand(t, null, true).applyTo(currentProgram, monitor);
                Function c = getFunctionContaining(t);
                if (c != null && !c.getEntryPoint().equals(t)) removeFunction(c);
                f = createFunction(t, null);
            }
            if (f == null) { out.println("##### could not create function at " + t); continue; }
            out.println("=== " + f.getName() + " @ " + t);
            DecompileResults r = di.decompileFunction(f, 120, monitor);
            out.println(r.decompileCompleted() ? r.getDecompiledFunction().getC() : "// decompile failed");
        }
        out.close();
    }
}
