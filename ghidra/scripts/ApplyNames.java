// Apply names.tsv (addr, func|label|create, A::B::name) from dti/names.py: functions are created where missing; existing
// non-default names are kept. "::" parts become class namespaces.
// args: names.tsv
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.nio.file.*;
import java.util.*;

public class ApplyNames extends GhidraScript {
    public void run() throws Exception {
        SymbolTable st = currentProgram.getSymbolTable();
        int fn = 0, made = 0, kept = 0, lab = 0, bad = 0, reset = 0;
        List<String> lines = Files.readAllLines(Paths.get(getScriptArgs()[0]));
        // names from an earlier run (ours: vfN / getDTI / DTI_init) that this list no longer gives -> default again
        Set<Long> listed = new HashSet<>();
        boolean naming = false;
        for (String line : lines) {
            String[] p = line.split("\t");
            listed.add(Long.parseLong(p[0], 16));
            if (p[1].equals("func")) naming = true;
        }
        if (naming) {
            for (Function f : currentProgram.getListing().getFunctions(true)) {
                if (ours(f) && !listed.contains(f.getEntryPoint().getOffset())) {
                    f.setParentNamespace(currentProgram.getGlobalNamespace());
                    f.setName(null, SourceType.DEFAULT);
                    reset++;
                }
            }
        }
        for (String line : lines) {
            String[] p = line.split("\t");
            Address a = toAddr(Long.parseLong(p[0], 16));
            String[] parts = p[2].split("::");
            Namespace ns = currentProgram.getGlobalNamespace();
            try {
                for (int i = 0; i < parts.length - 1; i++) {
                    Namespace n = st.getNamespace(parts[i], ns);
                    ns = n != null ? n : st.createClass(ns, parts[i], SourceType.ANALYSIS);
                }
                String name = parts[parts.length - 1];
                if (p[1].equals("create")) {   // a function start only (hidden.py)
                    if (getFunctionAt(a) == null && getFunctionContaining(a) == null) {
                        disassemble(a);
                        if (createFunction(a, null) != null) made++; else bad++;
                    }
                    continue;
                }
                if (p[1].equals("func")) {
                    Function f = getFunctionAt(a);
                    if (f == null) {
                        disassemble(a);
                        f = createFunction(a, null);
                        if (f == null) { bad++; continue; }
                        made++;
                    }
                    if (f.getSymbol().getSource() != SourceType.DEFAULT && !ours(f)) { kept++; continue; }
                    f.setParentNamespace(ns);
                    f.setName(name, SourceType.ANALYSIS);
                    fn++;
                } else {
                    st.createLabel(a, name, ns, SourceType.ANALYSIS);
                    lab++;
                }
            } catch (Exception e) {
                bad++;
            }
        }
        println(String.format("functions named %d (%d created), kept %d existing names, labels %d, failed %d, reset %d", fn, made, kept, lab, bad, reset));
    }

    boolean ours(Function f) {
        return f.getSymbol().getSource() == SourceType.ANALYSIS && f.getParentNamespace() instanceof GhidraClass
                && f.getName().matches("vf\\d+|getDTI|DTI_init");
    }
}
