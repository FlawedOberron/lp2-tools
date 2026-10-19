// Feasibility count for raising the 16-player cap: every instruction touching the per-player
// tables, and the 16-ish loop bounds in the functions that do.
// args: outfile
//   A: the static player table 0x1852080..0x18520bf (16 pointers, then the game pointer)
//   B: player info blocks: stride 0x900 or the game+0x52c80 start (DX11 run 2026-10-18)
//   C: game+0x28..0x67 (the infos pointer array), only in functions that load the game pointer 0x18520c0
//   bounds: cmp with 0xf / 0x10 / 0x11 in functions hit by A, B or C
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import ghidra.program.model.scalar.Scalar;
import ghidra.program.model.address.Address;
import java.io.*;
import java.util.*;

public class PlayerCapCount extends GhidraScript {
    long val(Object o) {
        if (o instanceof Scalar) return ((Scalar) o).getUnsignedValue();
        if (o instanceof Address) return ((Address) o).getOffset();
        return -1;
    }

    public void run() throws Exception {
        PrintWriter out = new PrintWriter(new FileWriter(getScriptArgs()[0]));
        Listing listing = currentProgram.getListing();
        Map<Function, int[]> hits = new TreeMap<>(Comparator.comparing(f -> f.getEntryPoint()));
        List<String> lines = new ArrayList<>();
        int[] total = new int[4];
        for (Instruction ins : listing.getInstructions(true)) {
            if (monitor.isCancelled()) break;
            Function f = getFunctionContaining(ins.getAddress());
            boolean a = false, b = false, game = false, c = false;
            for (int i = 0; i < ins.getNumOperands(); i++) {
                for (Object o : ins.getOpObjects(i)) {
                    long v = val(o);
                    if (v >= 0x1852080L && v < 0x18520c0L) a = true;
                    if (v == 0x18520c0L) game = true;
                    if (v == 0x900L || v == 0x52c80L) b = true;
                }
            }
            String text = ins.toString();
            if (!a && f != null && text.matches(".*\\+ 0x(2[8-9a-f]|[3-5][0-9a-f]|6[0-7])\\].*")) c = true;
            if (f == null) continue;
            int[] h = hits.computeIfAbsent(f, k -> new int[5]);
            if (game) h[4] = 1;
            if (a) { h[0]++; total[0]++; lines.add("A " + ins.getAddress() + " " + f.getName() + ": " + text); }
            if (b) { h[1]++; total[1]++; lines.add("B " + ins.getAddress() + " " + f.getName() + ": " + text); }
            if (c) h[2]++;
        }
        // bounds pass
        int funcs = 0;
        for (Map.Entry<Function, int[]> e : hits.entrySet()) {
            int[] h = e.getValue();
            boolean cHit = h[4] == 1 && h[2] > 0;
            if (!cHit) h[2] = 0;
            if (h[0] == 0 && h[1] == 0 && h[2] == 0) continue;
            funcs++;
            total[2] += h[2];
            for (Instruction ins : listing.getInstructions(e.getKey().getBody(), true)) {
                if (!ins.getMnemonicString().equalsIgnoreCase("CMP")) continue;
                for (Object o : ins.getOpObjects(1)) {
                    long v = val(o);
                    if (o instanceof Scalar && (v == 0xf || v == 0x10 || v == 0x11)) {
                        h[3]++; total[3]++;
                        lines.add("bound " + ins.getAddress() + " " + e.getKey().getName() + ": " + ins);
                    }
                }
            }
        }
        out.println("totals: A static table " + total[0] + ", B info stride/start " + total[1] + ", C game+0x28 array " + total[2]
                    + ", bounds " + total[3] + ", functions " + funcs);
        out.println();
        out.println("per function: A B C bounds");
        for (Map.Entry<Function, int[]> e : hits.entrySet()) {
            int[] h = e.getValue();
            if (h[0] + h[1] + h[2] == 0) continue;
            out.println(String.format("%s %-28s %3d %3d %3d %3d", e.getKey().getEntryPoint(), e.getKey().getName(), h[0], h[1], h[2], h[3]));
        }
        out.println();
        for (String l : lines) out.println(l);
        out.close();
    }
}
