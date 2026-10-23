// Whole-program export for grepping: every function's decompile plus indexes. Resumable (finished buckets are skipped).
// args: outdir [threads] [indexonly]
//   funcs/XXXX.c       functions whose entry is in the 64 KB range 0xXXXX0000, address order ("=== name @ addr")
//   functions.tsv      addr, name, size (bytes), bucket
//   calls.tsv          caller addr, callee addr
//   strings.tsv        string addr, functions referencing it (comma list), value (escaped)
//   vtables.tsv        addr, referenced (y/n), entry count, entry addrs: runs of 3+ pointers to function entries in data
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.mem.*;
import ghidra.program.model.symbol.*;
import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.*;

public class ExportAll extends GhidraScript {
    File out;

    public void run() throws Exception {
        String[] a = getScriptArgs();
        out = new File(a[0]);
        int threads = a.length > 1 ? Integer.parseInt(a[1]) : 4;
        new File(out, "funcs").mkdirs();
        Listing L = currentProgram.getListing();

        if (!new File(out, "functions.tsv").exists()) {
            println("indexes");
            writeIndexes(L);
        }
        if (a.length > 2 && a[2].equals("indexonly")) return;

        TreeMap<Long, List<Function>> buckets = new TreeMap<>();
        for (Function f : L.getFunctions(true)) {
            if (f.isThunk() && f.isExternal()) continue;
            buckets.computeIfAbsent(f.getEntryPoint().getOffset() >>> 16, k -> new ArrayList<>()).add(f);
        }
        int total = 0;
        for (List<Function> b : buckets.values()) total += b.size();
        println(total + " functions in " + buckets.size() + " buckets, " + threads + " threads");

        ExecutorService pool = Executors.newFixedThreadPool(threads);
        ThreadLocal<DecompInterface> tl = ThreadLocal.withInitial(() -> {
            DecompInterface di = new DecompInterface();
            di.openProgram(currentProgram);
            return di;
        });
        List<DecompInterface> all = Collections.synchronizedList(new ArrayList<>());
        int done = 0;
        long t0 = System.currentTimeMillis();
        for (Map.Entry<Long, List<Function>> e : buckets.entrySet()) {
            String name = String.format("%04x", e.getKey());
            File bf = new File(out, "funcs/" + name + ".c");
            List<Function> fs = e.getValue();
            if (bf.exists()) { done += fs.size(); continue; }
            List<Future<String>> res = new ArrayList<>();
            for (Function f : fs) {
                res.add(pool.submit(() -> {
                    DecompInterface di = tl.get();
                    if (!all.contains(di)) all.add(di);
                    DecompileResults r = di.decompileFunction(f, 90, monitor);
                    StringBuilder sb = new StringBuilder();
                    sb.append("=== ").append(f.getName(true)).append(" @ ").append(f.getEntryPoint()).append("\n");
                    if (r.decompileCompleted()) sb.append(r.getDecompiledFunction().getC());
                    else sb.append("// decompile failed: ").append(r.getErrorMessage()).append("\n");
                    return sb.toString();
                }));
            }
            File tmp = new File(out, "funcs/" + name + ".c.part");
            try (Writer w = new BufferedWriter(new FileWriter(tmp))) {
                for (Future<String> r : res) w.write(r.get());
            }
            Files.move(tmp.toPath(), bf.toPath(), StandardCopyOption.REPLACE_EXISTING);
            done += fs.size();
            long s = (System.currentTimeMillis() - t0) / 1000;
            println(String.format("bucket %s: %d / %d functions, %d s", name, done, total, s));
            if (monitor.isCancelled()) break;
        }
        pool.shutdown();
        pool.awaitTermination(1, TimeUnit.HOURS);
        for (DecompInterface di : all) di.dispose();
        new File(out, "DONE").createNewFile();
        println("done");
    }

    void writeIndexes(Listing L) throws Exception {
        try (PrintWriter fw = new PrintWriter(new BufferedWriter(new FileWriter(new File(out, "functions.tsv"))));
             PrintWriter cw = new PrintWriter(new BufferedWriter(new FileWriter(new File(out, "calls.tsv"))))) {
            for (Function f : L.getFunctions(true)) {
                Address ep = f.getEntryPoint();
                fw.println(ep + "\t" + f.getName(true) + "\t" + f.getBody().getNumAddresses() + "\t"
                        + String.format("%04x", ep.getOffset() >>> 16));
                for (Function c : f.getCalledFunctions(monitor)) cw.println(ep + "\t" + c.getEntryPoint());
            }
        }
        ReferenceManager rm = currentProgram.getReferenceManager();
        try (PrintWriter sw = new PrintWriter(new BufferedWriter(new FileWriter(new File(out, "strings.tsv"))))) {
            for (Data d : L.getDefinedData(true)) {
                if (!d.hasStringValue()) continue;
                Set<String> users = new TreeSet<>();
                for (Reference r : rm.getReferencesTo(d.getAddress())) {
                    Function f = getFunctionContaining(r.getFromAddress());
                    users.add(f != null ? f.getEntryPoint().toString() : r.getFromAddress().toString());
                }
                String v = String.valueOf(d.getValue()).replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r");
                sw.println(d.getAddress() + "\t" + String.join(",", users) + "\t" + v);
            }
        }
        Memory mem = currentProgram.getMemory();
        try (PrintWriter vw = new PrintWriter(new BufferedWriter(new FileWriter(new File(out, "vtables.tsv"))))) {
            for (MemoryBlock b : mem.getBlocks()) {
                if (b.isExecute() || !b.isInitialized()) continue;
                Address p = b.getStart();
                long n = b.getSize() / 4;
                List<String> run = new ArrayList<>();
                Address start = null;
                for (long i = 0; i <= n; i++) {
                    Function f = null;
                    Address at = null;
                    if (i < n) {
                        at = p.add(i * 4);
                        try {
                            long v = mem.getInt(at) & 0xffffffffL;
                            f = getFunctionAt(toAddr(v));
                        } catch (Exception ex) { f = null; }
                    }
                    if (f != null && (run.isEmpty() || !rm.hasReferencesTo(at))) {
                        if (run.isEmpty()) start = at;
                        run.add(f.getEntryPoint().toString());
                        continue;
                    }
                    if (run.size() >= 3)
                        vw.println(start + "\t" + (rm.hasReferencesTo(start) ? "y" : "n") + "\t" + run.size() + "\t" + String.join(",", run));
                    run.clear();
                    if (f != null) { start = at; run.add(f.getEntryPoint().toString()); }
                }
            }
        }
    }
}
