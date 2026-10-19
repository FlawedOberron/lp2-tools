// Decompile every function that calls the given imported xlive ordinals.
// args: outfile ordinal1 ordinal2 ...
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.util.*;

public class DecompImportCallers extends GhidraScript {
    public void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter out = new PrintWriter(new FileWriter(a[0]));
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        Set<String> wanted = new HashSet<>();
        for (int i = 1; i < a.length; i++) wanted.add(a[i]);
        Set<Function> done = new HashSet<>();
        SymbolIterator si = currentProgram.getSymbolTable().getExternalSymbols();
        while (si.hasNext()) {
            Symbol s = si.next();
            String n = s.getName();
            String ord = n.startsWith("Ordinal_") ? n.substring(8) : n;
            if (!wanted.contains(ord)) continue;
            out.println("##### " + s.getParentNamespace() + "::" + n);
            List<Address> sites = new ArrayList<>();
            for (Reference r : s.getReferences()) sites.add(r.getFromAddress());
            // thunks / IAT slots: follow one more level
            for (Address site : new ArrayList<>(sites)) {
                Function th = getFunctionContaining(site);
                if (th == null) for (Reference r : getReferencesTo(site)) sites.add(r.getFromAddress());
            }
            for (Address site : sites) {
                Function f = getFunctionContaining(site);
                if (f == null) continue;
                out.println("call at " + site + " in " + f.getName() + " @" + f.getEntryPoint());
                if (!done.add(f)) continue;
                DecompileResults r = di.decompileFunction(f, 60, monitor);
                out.println(r.decompileCompleted() ? r.getDecompiledFunction().getC() : "// decompile failed");
            }
        }
        out.close();
    }
}
