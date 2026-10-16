// Decompile every function whose entry lies in [start, end).  args: outfile start end
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.*;
import java.io.*;

public class DecompRange extends GhidraScript {
    public void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter out = new PrintWriter(new FileWriter(a[0]));
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        long s = Long.parseLong(a[1], 16), e = Long.parseLong(a[2], 16);
        for (Function f : currentProgram.getFunctionManager().getFunctions(toAddr(s), true)) {
            if (f.getEntryPoint().getOffset() >= e) break;
            DecompileResults res = di.decompileFunction(f, 120, monitor);
            out.println("=== " + f.getName() + " @ " + f.getEntryPoint() + "  callers:");
            for (Function c : f.getCallingFunctions(monitor)) out.println("//   " + c.getName() + "@" + c.getEntryPoint());
            out.println(res.decompileCompleted() ? res.getDecompiledFunction().getC() : "(decompile failed)");
        }
        out.close();
    }
}
