// Decompile every function that references the given addresses.
// args: outfile addr1 addr2 ...
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.util.*;

public class DecompRefs extends GhidraScript {
    public void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter out = new PrintWriter(new FileWriter(a[0]));
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        Set<Function> done = new HashSet<>();
        for (int i = 1; i < a.length; i++) {
            Address t = toAddr(a[i]);
            out.println("##### refs to " + t);
            List<Address> froms = new ArrayList<>();
            for (Reference r : getReferencesTo(t)) froms.add(r.getFromAddress());
            long v = t.getOffset();
            InstructionIterator it = currentProgram.getListing().getInstructions(true);
            while (it.hasNext()) {
                Instruction ins = it.next();
                for (int op = 0; op < ins.getNumOperands(); op++)
                    for (Object o : ins.getOpObjects(op))
                        if (o instanceof ghidra.program.model.scalar.Scalar && ((ghidra.program.model.scalar.Scalar) o).getUnsignedValue() == v
                            && !froms.contains(ins.getAddress())) froms.add(ins.getAddress());
            }
            for (Address from : froms) {
                Function f = getFunctionContaining(from);
                out.println("  from " + from + " in " + (f == null ? "?" : f.getName() + "@" + f.getEntryPoint()));
                if (f == null || !done.add(f)) continue;
                DecompileResults res = di.decompileFunction(f, 120, monitor);
                out.println("=== " + f.getName() + " @ " + f.getEntryPoint());
                out.println(res.decompileCompleted() ? res.getDecompiledFunction().getC() : "(decompile failed: " + res.getErrorMessage() + ")");
            }
        }
        out.close();
    }
}
