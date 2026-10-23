// Apply structs.tsv (dti/structs.py): each class's structure (sized from its DTI, named fields, vftable at 0), and
// `this` typed as that class in its __thiscall functions (an explicit ECX first parameter becomes the auto `this`).
// args: structs.tsv
import ghidra.app.script.GhidraScript;
import ghidra.program.model.data.*;
import ghidra.program.model.listing.*;
import ghidra.program.model.listing.Function.FunctionUpdateType;
import ghidra.program.model.symbol.*;
import java.nio.file.*;
import java.util.*;

public class ApplyStructs extends GhidraScript {
    public void run() throws Exception {
        DataTypeManager dtm = currentProgram.getDataTypeManager();
        SymbolTable st = currentProgram.getSymbolTable();
        Map<String, DataType> prim = new HashMap<>();
        prim.put("bool", BooleanDataType.dataType); prim.put("byte", ByteDataType.dataType);
        prim.put("sbyte", SignedByteDataType.dataType); prim.put("ushort", UnsignedShortDataType.dataType);
        prim.put("short", ShortDataType.dataType); prim.put("uint", UnsignedIntegerDataType.dataType);
        prim.put("int", IntegerDataType.dataType); prim.put("ulonglong", UnsignedLongLongDataType.dataType);
        prim.put("longlong", LongLongDataType.dataType); prim.put("float", FloatDataType.dataType);
        prim.put("double", DoubleDataType.dataType); prim.put("pointer", PointerDataType.dataType);
        int ns = 0, nf = 0, fixed = 0, bad = 0;
        Structure cur = null;
        Set<GhidraClass> classes = new LinkedHashSet<>();
        for (String line : Files.readAllLines(Paths.get(getScriptArgs()[0]))) {
            String[] p = line.split("\t");
            try {
                if (p[0].equals("S")) {
                    if (cur != null) dtm.addDataType(cur, DataTypeConflictHandler.REPLACE_HANDLER);
                    cur = null;
                    Namespace n = currentProgram.getGlobalNamespace();
                    for (String part : p[1].split("::")) {
                        Namespace c = st.getNamespace(part, n);
                        n = c != null ? c : st.createClass(n, part, SourceType.ANALYSIS);
                    }
                    if (!(n instanceof GhidraClass)) n = st.convertNamespaceToClass(n);
                    GhidraClass gc = (GhidraClass) n;
                    classes.add(gc);
                    // a fresh structure where the class's `this` type lives (findOrCreateClassStruct's path), added to the
                    // data type manager below, replacing an empty placeholder
                    Structure ref = VariableUtilities.findOrCreateClassStruct(gc, dtm);
                    int size = Integer.parseInt(p[2]);
                    Structure s = new StructureDataType(ref.getCategoryPath(), ref.getName(), size, dtm);
                    s.replaceAtOffset(0, PointerDataType.dataType, 4, "vftable", null);
                    cur = s;
                    ns++;
                } else if (cur != null) {
                    int off = Integer.parseInt(p[1]);
                    if (off == 0) continue;
                    cur.replaceAtOffset(off, prim.get(p[2]), Integer.parseInt(p[3]), p[4], null);
                    nf++;
                }
            } catch (Exception e) {
                bad++;
            }
        }
        if (cur != null) dtm.addDataType(cur, DataTypeConflictHandler.REPLACE_HANDLER);
        // `this` for the classes' functions
        for (GhidraClass gc : classes) {
            for (Symbol s : st.getSymbols(gc)) {
                if (s.getSymbolType() != SymbolType.FUNCTION) continue;
                Function f = getFunctionAt(s.getAddress());
                if (f == null) continue;
                try {
                    String n = f.getName();
                    if (!(n.matches("vf\\d+") || n.equals("getDTI"))) continue;   // members for sure (DTI_init is static)
                    Parameter[] ps = f.getParameters();
                    if (ps.length > 0 && ps[0].isAutoParameter()) continue;
                    if (ps.length > 0 && ps[0].isRegisterVariable() && ps[0].getRegister().getName().equals("ECX")) {
                        List<Parameter> rest = new ArrayList<>(Arrays.asList(ps).subList(1, ps.length));
                        f.updateFunction("__thiscall", f.getReturn(), rest, FunctionUpdateType.DYNAMIC_STORAGE_ALL_PARAMS, true, SourceType.ANALYSIS);
                    } else if (ps.length == 0) {
                        f.setCallingConvention("__thiscall");   // no stored parameters: the decompiler still infers the rest
                    } else continue;
                    fixed++;
                } catch (Exception e) {
                    bad++;
                }
            }
        }
        println(String.format("structs %d, fields %d, functions given a typed this %d, failed %d", ns, nf, fixed, bad));
    }
}
