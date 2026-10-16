// Print the instructions (address, bytes, text) of the functions at the given addresses.
// args: outfile addr1 addr2 ...
import ghidra.app.script.GhidraScript;
import ghidra.program.model.listing.*;
import java.io.*;

public class DumpAsm extends GhidraScript {
    public void run() throws Exception {
        String[] a = getScriptArgs();
        PrintWriter out = new PrintWriter(new FileWriter(a[0]));
        for (int i = 1; i < a.length; i++) {
            Function f = getFunctionAt(toAddr(a[i]));
            if (f == null) { out.println("no function at " + a[i]); continue; }
            out.println("=== " + f.getName());
            for (Instruction ins : currentProgram.getListing().getInstructions(f.getBody(), true)) {
                StringBuilder hex = new StringBuilder();
                for (byte b : ins.getBytes()) hex.append(String.format("%02x", b));
                out.println(ins.getAddress() + "  " + String.format("%-20s", hex) + " " + ins);
            }
        }
        out.close();
    }
}
