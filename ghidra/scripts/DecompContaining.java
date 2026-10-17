// Decompile the functions at the given addresses, and (with "+callers") every caller of them.
// args: outfile [+callers] addr1 addr2 ...
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import java.io.*;
import java.util.*;

public class DecompContaining extends GhidraScript {
    public void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter out = new PrintWriter(new FileWriter(a[0]));
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        boolean callers = false;
        Set<Function> done = new LinkedHashSet<>();
        for (int i = 1; i < a.length; i++) {
            if (a[i].equals("+callers")) { callers = true; continue; }
            Function f = getFunctionContaining(toAddr(a[i]));
            if (f == null) { out.println("##### no function at " + a[i]); continue; }
            done.add(f);
            if (callers) for (Function c : f.getCallingFunctions(monitor)) done.add(c);
        }
        for (Function f : done) {
            DecompileResults res = di.decompileFunction(f, 120, monitor);
            out.println("=== " + f.getName() + " @ " + f.getEntryPoint() + "  callers:");
            for (Function c : f.getCallingFunctions(monitor)) out.println("//   " + c.getName() + "@" + c.getEntryPoint());
            out.println(res.decompileCompleted() ? res.getDecompiledFunction().getC() : "(decompile failed: " + res.getErrorMessage() + ")");
        }
        out.close();
    }
}
