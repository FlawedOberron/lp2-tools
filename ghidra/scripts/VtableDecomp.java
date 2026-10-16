// Find vtables containing a function and decompile every entry.
// args: outfile funcaddr [maxEntries]
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.util.*;

public class VtableDecomp extends GhidraScript {
    boolean isFunc(Address a) {
        try {
            int v = currentProgram.getMemory().getInt(a);
            Address t = toAddr(v & 0xffffffffL);
            return getFunctionAt(t) != null;
        } catch (Exception e) { return false; }
    }
    public void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter out = new PrintWriter(new FileWriter(a[0]));
        long target = Long.decode(a[1]);
        int max = a.length > 2 ? Integer.parseInt(a[2]) : 80;
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        Memory mem = currentProgram.getMemory();
        byte[] pat = new byte[]{(byte) target, (byte) (target >> 8), (byte) (target >> 16), (byte) (target >> 24)};
        Address p = currentProgram.getMinAddress();
        Set<Function> done = new HashSet<>();
        while ((p = mem.findBytes(p, pat, null, true, monitor)) != null) {
            if (p.getOffset() % 4 == 0 && getFunctionContaining(p) == null) {
                Address start = p;
                while (isFunc(start.subtract(4))) start = start.subtract(4);
                out.println("##### vtable " + start + " (entry at " + p + ")");
                for (int i = 0; i < max; i++) {
                    Address e = start.add(4 * i);
                    if (!isFunc(e)) break;
                    Function f = getFunctionAt(toAddr(mem.getInt(e) & 0xffffffffL));
                    out.println("// [" + i + "] +" + Integer.toHexString(4 * i) + " " + f.getName());
                    if (done.add(f)) {
                        DecompileResults r = di.decompileFunction(f, 60, monitor);
                        if (r.decompileCompleted()) out.println(r.getDecompiledFunction().getC());
                    }
                }
            }
            p = p.add(1);
        }
        out.close();
    }
}
