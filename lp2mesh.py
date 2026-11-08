#!/usr/bin/env python3
"""The map editor's mesh builder: OBJ / glTF files -> placeable pieces, and the project's material library.

  lp2mesh.py import --game LP2_DIR PROJECT FILE [--name N] [--collision mesh|box|none] [--scale S] [--mat SRC=MAT ...]
  lp2mesh.py rebuild --game LP2_DIR PROJECT NAME [--collision ...] [--scale S] [--mat SRC=MAT ...]
  lp2mesh.py material --game LP2_DIR PROJECT NAME [--bm IMG] [--nm IMG] [--mm IMG] [--colour R,G,B] [--size N]
                       [--grid M] [--blockout]
  lp2mesh.py import ... --split                 one piece per Blender object (see "Split" below)
  lp2mesh.py delete PROJECT NAME
  lp2mesh.py list PROJECT                        imports and materials as JSON

An import is a small library map of its own, PROJECT/imports/<name>/ (lp2props.py's layout: .preview/stage/...
/online00.rModel with its rTextures, .preview/geo.json, assets/collision.sbc1, project.json), placed through the
foreign-copy path as "@project/imports/<name>" (lp2pieces.map_folder). The whole file is one piece; its source is
kept in imports/<name>/source/ so it can be rebuilt (other collision, materials, scale).
Collision: mesh = its own triangles, box = its bounding box (12 triangles), none = walk / shoot through.

Materials: PROJECT/materials/<name>/material.json {bm, nm, mm: image file names beside it, colour: [r, g, b] when
there is no colour map, size: the largest side}. Built as rTextures (lp2tex.py) named um_<name>_bm / _nm / _mm in
the stage folder, so imports that share a material (a trim sheet) share its textures in the map's memory.
A file's own materials become project materials named after them (an existing one of that name is reused, so
meshes from one source file share their sheets); --mat SRC=MAT maps a file material to a project one.
import.json "unwrap": M (rebuild --unwrap; the editor's Lazy unwrap) does the same as a material's "grid" for one
mesh, for files without usable UVs.
import.json "blockout": true (rebuild --blockout 1; the editor's Blockout) ignores the file's materials and colours the
faces by facing: walkable floors (up to the navmesh's 50 degrees) blockout_floor (orange), walls blockout_wall
(grey-white), ceilings blockout_ceiling (dark grey); project materials made on first use (blockout grid, 1 m), so
they can be recoloured like any other. Window faces (import.json "windows": regions painted in the editor, rebuild
--window; or a file material named window / glass) get blockout_window: a see-through cut-out grid, no bake shadow.
No normal map = flat; no mask map = black (lp2stage.py's defaults for LP1 materials without them).
"grid": M (--grid; 0 = off) replaces the mesh's UVs with world-projected ones, one texture tile per M metres of the
piece's own space (each face takes the axis plane it faces most; a scaled piece stretches it).
--blockout: the colour map becomes a generated blockout grid (blockout_image: one tile = 1 m, white lines every
metre / 25 cm / 12.5 cm on the material's colour, default orange) and "grid" 1 unless one is set.

Split (--split, NAME = the set): one import per drawn object, imports/<set>_<object>/ (object = Blender's name
without .001), sharing the source in imports/<set>/source/ with imports/<set>/group.json {source, from, members,
layout: [{piece, M: 16 floats, editor metres, row-major}], pivot: the set's bottom centre (metres)}. A piece's
vertices are in its object's own space (glTF: the node's origin / rotation / scale; OBJ, which bakes them: origin at
the object's bottom centre), so it places like the object; the layout puts every object back where it was (the
editor's Place set). glTF objects sharing a mesh (Alt+D linked duplicates) of one name are one piece placed several
times; other repeats of a name become <object>_2... COL_<object> goes with its object's piece.
A re-import keeps imports of objects no longer in the file ("missing": true, not rebuilt).

Space: glTF and Blender's OBJ export (Y up) match LP2's axes; positions are metres * --scale (100: cm).
Vertex colours (glTF COLOR_0, OBJ "v x y z r g b") tint the baked light, which is otherwise lp2props.py's top light.
"""
import argparse, base64, hashlib, json, os, re, shutil, struct, sys
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lp2col, lp2mapc, lp2pieces, lp2preview, lp2props, lp2tex  # noqa: E402

MAX_TEX = 2048
KINDS = ("bm", "nm", "mm")


def progress(f, text=""):
    print(f"@progress {f:.3f} {text}", flush=True)


def slug(s, n=24):
    s = re.sub(r"[^a-z0-9_]+", "_", s.lower()).strip("_")[:n].strip("_")   # the same again when re-slugged
    return s or "mesh"


# ---------------------------------------------------------------- readers: -> (parts, materials)
# part: dict(mat=source material name, P (n, 3), N (n, 3) | None, U (n, 2) | None, C (n, 3) | None, T (m, 3))
# material: name -> dict(bm=(file name, bytes) | None, nm=..., colour=(r, g, b) 0..1)

def read_obj(path):
    folder = os.path.dirname(path)
    V, C, VT, VN = [], [], [], []
    faces = {}   # material -> [corner triples]
    cur, obj = "", ""
    mtls = []
    for line in open(path, encoding="utf-8", errors="replace"):
        w = line.split()
        if not w:
            continue
        if w[0] == "v":
            V.append([float(x) for x in w[1:4]])
            C.append([float(x) for x in w[4:7]] if len(w) >= 7 else None)
        elif w[0] == "vt":
            VT.append([float(w[1]), float(w[2]) if len(w) > 2 else 0.0])
        elif w[0] == "vn":
            VN.append([float(x) for x in w[1:4]])
        elif w[0] in ("o", "g"):
            obj = " ".join(w[1:])
        elif w[0] == "usemtl":
            cur = " ".join(w[1:])
        elif w[0] == "mtllib":
            mtls.append(" ".join(w[1:]))
        elif w[0] == "f":
            cs = []
            for c in w[1:]:
                k = (c.split("/") + ["", ""])[:3]
                idx = [int(x) if x else 0 for x in k]
                cs.append(tuple(i - 1 if i > 0 else (len(L) + i if i < 0 else -1)
                                for i, L in zip(idx, (V, VT, VN))))
            for i in range(1, len(cs) - 1):   # fan
                faces.setdefault((obj, cur), []).append((cs[0], cs[i], cs[i + 1]))
    V = np.array(V, np.float64)
    has_c = any(c is not None for c in C)
    Cv = np.array([c if c is not None else [1.0, 1.0, 1.0] for c in C], np.float64) if has_c else None
    VT, VN = np.array(VT, np.float64).reshape(-1, 2), np.array(VN, np.float64).reshape(-1, 3)
    parts = []
    for (obj, mat), fs in faces.items():
        keys, T = {}, []
        for f in fs:
            tri = []
            for c in f:
                if c not in keys:
                    keys[c] = len(keys)
                tri.append(keys[c])
            T.append(tri)
        ks = list(keys)
        vi = np.array([k[0] for k in ks])
        ti = np.array([k[1] for k in ks])
        ni = np.array([k[2] for k in ks])
        U = None
        if len(VT) and (ti >= 0).all():
            U = VT[ti].copy()
            U[:, 1] = 1.0 - U[:, 1]   # OBJ V is up from the bottom; LP2's (and glTF's) down from the top
        N = VN[ni] if len(VN) and (ni >= 0).all() else None
        parts.append(dict(obj=obj, mat=mat, P=V[vi], N=N, U=U, C=Cv[vi] if Cv is not None else None, T=np.array(T, np.int64)))
    mats = {}
    for m in mtls:
        mp = os.path.join(folder, m)
        if not os.path.exists(mp):
            continue
        name = None
        for line in open(mp, encoding="utf-8", errors="replace"):
            w = line.split()
            if not w:
                continue
            if w[0] == "newmtl":
                name = " ".join(w[1:])
                mats[name] = dict(bm=None, nm=None, colour=(0.8, 0.8, 0.8))
            elif name is None:
                continue
            elif w[0] == "Kd":
                mats[name]["colour"] = tuple(float(x) for x in w[1:4])
            elif w[0] in ("map_Kd", "map_Bump", "map_bump", "bump", "norm", "map_Kn"):
                f = w[-1]   # options (-bm 1.0 ...) come first
                fp = os.path.join(folder, f.replace("\\", "/"))
                if os.path.exists(fp):
                    mats[name]["bm" if w[0] == "map_Kd" else "nm"] = (os.path.basename(fp), open(fp, "rb").read())
    return parts, mats


GL_TYPES = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
GL_SIZE = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def read_gltf(path):
    raw = open(path, "rb").read()
    folder = os.path.dirname(path)
    bin_chunk = None
    if raw[:4] == b"glTF":
        o, J = 12, None
        while o < len(raw):
            ln, kind = struct.unpack_from("<II", raw, o)
            if kind == 0x4E4F534A:
                J = json.loads(raw[o + 8:o + 8 + ln])
            elif kind == 0x004E4942:
                bin_chunk = raw[o + 8:o + 8 + ln]
            o += 8 + ln
    else:
        J = json.loads(raw)

    def uri_bytes(uri):
        if uri.startswith("data:"):
            return base64.b64decode(uri.split(",", 1)[1])
        from urllib.parse import unquote
        return open(os.path.join(folder, unquote(uri)), "rb").read()

    buffers = [uri_bytes(b["uri"]) if "uri" in b else bin_chunk for b in J.get("buffers", [])]

    def view_bytes(i):
        bv = J["bufferViews"][i]
        o = bv.get("byteOffset", 0)
        return buffers[bv["buffer"]][o:o + bv["byteLength"]], bv.get("byteStride")

    def accessor(i):
        a = J["accessors"][i]
        dt, k, n = np.dtype(GL_TYPES[a["componentType"]]), GL_SIZE[a["type"]], a["count"]
        if "bufferView" not in a:
            out = np.zeros((n, k), np.float64)
        else:
            data, stride = view_bytes(a["bufferView"])
            o = a.get("byteOffset", 0)
            stride = stride or dt.itemsize * k
            rows = np.frombuffer(data, np.uint8, count=stride * (n - 1) + dt.itemsize * k, offset=o)
            rows = np.lib.stride_tricks.as_strided(rows, (n, dt.itemsize * k), (stride, 1))
            out = np.ascontiguousarray(rows).view(dt).reshape(n, k).astype(np.float64)
            if a.get("normalized"):
                out /= float(np.iinfo(dt).max)
        if "sparse" in a:
            s = a["sparse"]
            idx_d, _ = view_bytes(s["indices"]["bufferView"])
            ii = np.frombuffer(idx_d, GL_TYPES[s["indices"]["componentType"]], s["count"], s["indices"].get("byteOffset", 0))
            val_d, _ = view_bytes(s["values"]["bufferView"])
            vv = np.frombuffer(val_d, dt, s["count"] * k, s["values"].get("byteOffset", 0)).reshape(-1, k)
            out[ii.astype(np.int64)] = vv
        return out

    def image(tex_ref):
        if not tex_ref:
            return None
        src = J["textures"][tex_ref["index"]].get("source")
        if src is None:
            return None
        im = J["images"][src]
        if "uri" in im:
            data = uri_bytes(im["uri"])
            name = os.path.basename(im["uri"]) if not im["uri"].startswith("data:") else f"image{src}.png"
        else:
            data = view_bytes(im["bufferView"])[0]
            name = (im.get("name") or f"image{src}") + (".jpg" if "jpeg" in im.get("mimeType", "") else ".png")
        return name, bytes(data)

    mats = {}
    names = []
    for k, m in enumerate(J.get("materials", [])):
        name = m.get("name") or f"material{k}"
        names.append(name)
        pbr = m.get("pbrMetallicRoughness", {})
        sg = m.get("extensions", {}).get("KHR_materials_pbrSpecularGlossiness", {})   # older exports (Sketchfab...)
        bm = image(pbr.get("baseColorTexture")) or image(sg.get("diffuseTexture"))
        colour = pbr.get("baseColorFactor") or sg.get("diffuseFactor") or [1, 1, 1, 1]
        mats[name] = dict(bm=bm, nm=image(m.get("normalTexture")), colour=tuple(colour[:3]))

    def node_matrix(n):
        if "matrix" in n:
            return np.array(n["matrix"], np.float64).reshape(4, 4).T
        t = np.array(n.get("translation", [0, 0, 0]), np.float64)
        x, y, z, w = n.get("rotation", [0, 0, 0, 1])
        r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                      [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                      [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
        s = np.array(n.get("scale", [1, 1, 1]), np.float64)
        M = np.eye(4)
        M[:3, :3] = r * s
        M[:3, 3] = t
        return M

    parts = []

    def walk(i, parent):
        n = J["nodes"][i]
        M = parent @ node_matrix(n)
        if "mesh" in n:
            for pr in J["meshes"][n["mesh"]]["primitives"]:
                if pr.get("mode", 4) != 4:
                    continue
                at = pr["attributes"]
                P = accessor(at["POSITION"])
                T = accessor(pr["indices"]).astype(np.int64).reshape(-1, 3) if "indices" in pr else \
                    np.arange(len(P)).reshape(-1, 3)
                P = P @ M[:3, :3].T + M[:3, 3]
                N = accessor(at["NORMAL"]) @ np.linalg.inv(M[:3, :3]) if "NORMAL" in at else None
                if np.linalg.det(M[:3, :3]) < 0:
                    T = T[:, ::-1]
                U = accessor(at["TEXCOORD_0"]) if "TEXCOORD_0" in at else None
                C = accessor(at["COLOR_0"])[:, :3] if "COLOR_0" in at else None
                mi = pr.get("material")
                parts.append(dict(obj=n.get("name", ""), mat=names[mi] if mi is not None else "", P=P, N=N, U=U, C=C, T=T,
                                  node=i, mesh=n["mesh"], M=M))
        for c in n.get("children", []):
            walk(c, M)

    scene = J.get("scenes", [{}])[J.get("scene", 0)] if J.get("scenes") else {"nodes": range(len(J.get("nodes", [])))}
    for i in scene.get("nodes", []):
        walk(i, np.eye(4))
    return parts, mats


def obj_key(obj):
    """Blender's object name, without the .001 a duplicate gets"""
    return re.sub(r"\.\d{3}$", "", obj).lower()


def is_col(obj):
    return obj[:4].upper() == "COL_"


def read_mesh(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".obj":
        return read_obj(path)
    if ext in (".gltf", ".glb"):
        return read_gltf(path)
    raise SystemExit(f"{path}: not an OBJ or glTF file")


def source_files(path):
    """the file and what it points at (OBJ: mtl files and their maps; .gltf: buffers and images) -> [relative]"""
    folder, ext = os.path.dirname(path), os.path.splitext(path)[1].lower()
    out = [os.path.basename(path)]
    refs = []
    if ext == ".obj":
        for line in open(path, encoding="utf-8", errors="replace"):
            if line.startswith("mtllib"):
                m = line.split(None, 1)[1].strip()
                refs.append(m)
                mp = os.path.join(folder, m)
                if os.path.exists(mp):
                    for l2 in open(mp, encoding="utf-8", errors="replace"):
                        w = l2.split()
                        if w and w[0] in ("map_Kd", "map_Bump", "map_bump", "bump", "norm", "map_Kn"):
                            refs.append(w[-1].replace("\\", "/"))
    elif ext == ".gltf":
        from urllib.parse import unquote
        J = json.load(open(path))
        refs = [unquote(x["uri"]) for x in J.get("buffers", []) + J.get("images", []) if "uri" in x and not x["uri"].startswith("data:")]
    return out + [r for r in refs if os.path.exists(os.path.join(folder, r))]


# ---------------------------------------------------------------- materials

def mat_dir(project, name):
    return os.path.join(project, "materials", name)


def load_material(project, name):
    old = mat_dir(project, name + "_")   # made by an older slug() cut at a "_" (re-slugged names lost it)
    if not os.path.exists(mat_dir(project, name)) and os.path.exists(os.path.join(old, "material.json")):
        os.rename(old, mat_dir(project, name))
    p = os.path.join(mat_dir(project, name), "material.json")
    return json.load(open(p)) if os.path.exists(p) else None


def save_material(project, name, m):
    os.makedirs(mat_dir(project, name), exist_ok=True)
    json.dump(m, open(os.path.join(mat_dir(project, name), "material.json"), "w"), indent=1)


def pot(n, cap):
    p = 4
    while p < n and p < cap:
        p *= 2
    return p


def load_image(path, size):
    from PIL import Image
    im = Image.open(path).convert("RGBA")
    w, h = pot(im.width, size), pot(im.height, size)
    if (w, h) != im.size:
        im = im.resize((w, h), Image.LANCZOS)
    return np.asarray(im)


BLOCKOUT_ORANGE = (0.93, 0.47, 0.16)
# import.json "blockout": material per facing (floor: normal y >= cos 50 degrees, the navmesh's walkable slope)
BLOCKOUT_FACINGS = {"floor": (0.93, 0.47, 0.16), "wall": (0.82, 0.82, 0.80), "ceiling": (0.30, 0.30, 0.31),
                    "window": (0.45, 0.78, 0.98)}
# faces become "window" when painted in the editor (import.json "windows": seeds, see window_faces) or when their file
# material's name says so; their material is a cut-out grid ("cutout": alpha-tested in game, word0 | 0x4000) that
# casts no shadow in the bake ("shadow": false)
WINDOW_NAMES = ("window", "glass")


def window_image(colour, px=512):
    """a see-through grid tile (1 m): a bold frame round the edge, bars every 25 cm, thin lines every 12.5 cm; the
    panes clear -> RGBA uint8 (alpha 0 / 255: the game cuts it out)"""
    y, x = np.mgrid[0:px, 0:px]
    def d(step):
        return np.minimum(np.minimum(x % step, step - 1 - x % step), np.minimum(y % step, step - 1 - y % step))
    solid = (d(px) < 6) | (d(px // 4) < 2) | (d(px // 8) < 1)
    base = np.array([255 * c for c in colour], np.float32)
    img = np.where((d(px) < 6)[..., None], base * 0.7, base)
    a = np.where(solid, 255, 0).astype(np.uint8)[..., None]
    return np.concatenate([np.clip(img, 0, 255).astype(np.uint8), a], 2)


def window_faces(P, T, seeds, scale):
    """import.json "windows": [[x, y, z, nx, ny, nz, erase?]] in the editor's metres in the piece's own space (a click on
    a face). Each paints (or with erase 1, unpaints) the flat region it lands in: the triangle under the point, and
    those joined to it by edges that lie in its plane. -> bool per triangle"""
    out = np.zeros(len(T), bool)
    if not seeds or not len(T):
        return out
    Pc = P * scale / 100.0   # metres, as the editor's
    a, b, c = Pc[T[:, 0]], Pc[T[:, 1]], Pc[T[:, 2]]
    n = np.cross(b - a, c - a)
    area2 = np.linalg.norm(n, axis=1)
    n = n / np.maximum(area2, 1e-12)[:, None]
    off = (n * a).sum(1)
    key = [tuple(v) for v in np.round(Pc * 1000).astype(np.int64)]   # 1 mm weld for the edges
    edges = {}
    for t, tri in enumerate(T):
        for i in range(3):
            e = tuple(sorted((key[tri[i]], key[tri[(i + 1) % 3]])))
            edges.setdefault(e, []).append(t)
    for sd in seeds:
        p, sn = np.array(sd[:3], float), np.array(sd[3:6], float)
        erase = len(sd) > 6 and bool(sd[6])
        dist = np.abs((n * p).sum(1) - off)
        ok = (dist < 0.02) & ((n * sn).sum(1) > 0.9)
        # inside the triangle (barycentric, a little slack)
        v0, v1, v2 = b - a, c - a, p - a
        d00, d01, d11 = (v0 * v0).sum(1), (v0 * v1).sum(1), (v1 * v1).sum(1)
        d20, d21 = (v2 * v0).sum(1), (v2 * v1).sum(1)
        den = np.maximum(d00 * d11 - d01 * d01, 1e-12)
        bv = (d11 * d20 - d01 * d21) / den
        bw = (d00 * d21 - d01 * d20) / den
        ok &= (bv >= -0.01) & (bw >= -0.01) & (bv + bw <= 1.01)
        hits = np.nonzero(ok)[0]
        if not len(hits):
            continue
        start = int(hits[np.argmin(dist[hits])])
        region, todo = {start}, [start]
        while todo:
            t = todo.pop()
            tri = T[t]
            for i in range(3):
                for u in edges[tuple(sorted((key[tri[i]], key[tri[(i + 1) % 3]])))]:
                    if u not in region and (n[u] * n[start]).sum() > 0.999 and abs(off[u] - off[start]) < 0.01:
                        region.add(u)
                        todo.append(u)
        out[list(region)] = not erase
    return out
BLOCKOUT_FLOOR_Y = 0.6428


def blockout_image(colour=BLOCKOUT_ORANGE, px=512):
    """a dev-texture style tile (1 m): the colour in 50 cm checks a shade apart, white lines every 12.5 cm
    (faint), 25 cm and a bold one round the edge -> RGBA uint8"""
    base = np.array([255 * c for c in colour], np.float32)
    y, x = np.mgrid[0:px, 0:px]
    q = px // 2
    img = np.where((((x // q) + (y // q)) % 2 == 0)[..., None], base, base * 0.88)
    def lines(step, half, alpha):
        d = np.minimum(np.minimum(x % step, step - 1 - x % step), np.minimum(y % step, step - 1 - y % step))
        return np.where(d < half, alpha, 0.0)
    a = np.maximum.reduce([lines(px // 8, 1, 0.22), lines(px // 4, 1, 0.5), lines(px, 4, 1.0)])[..., None]
    img = img * (1 - a) + 255 * a
    return np.concatenate([np.clip(img, 0, 255).astype(np.uint8), np.full((px, px, 1), 255, np.uint8)], 2)


def grid_uvs(P, T, N, tile):
    """unshared vertices with box-projected UVs, tile cm per texture repeat -> P, T, N, U"""
    P, N = P[T].reshape(-1, 3), (N[T].reshape(-1, 3) if N is not None else None)
    a, b, c = P[0::3], P[1::3], P[2::3]
    fn = np.abs(np.cross(b - a, c - a))
    axis = np.repeat(np.argmax(fn, 1), 3)
    U = np.where(axis[:, None] == 0, P[:, [2, 1]], np.where(axis[:, None] == 1, P[:, [0, 2]], P[:, [0, 1]])) / tile
    U[axis != 1, 1] *= -1   # walls: texture up = world up
    c = np.ascontiguousarray
    return c(P), np.arange(len(P)).reshape(-1, 3), (c(N) if N is not None else None), c(U)


def build_material(project, name):
    """the material's rTextures in materials/<name>/build/ (rebuilt when material.json or an image changes)
    -> {kind: path}"""
    m = load_material(project, name)
    if m is None:
        raise SystemExit(f"no material {name} in {project}/materials")
    d = mat_dir(project, name)
    build = os.path.join(d, "build")
    key = json.dumps(m, sort_keys=True)
    for k in KINDS:
        if m.get(k):
            st = os.stat(os.path.join(d, m[k]))
            key += f"|{k}:{st.st_size}:{st.st_mtime_ns}"
    leaf = {k: f"um_{slug(name)}_{k}" for k in KINDS}
    out = {k: os.path.join(build, leaf[k] + ".rTexture") for k in KINDS}
    kp = os.path.join(build, "build.key")
    if os.path.exists(kp) and open(kp).read() == key and all(os.path.exists(p) for p in out.values()):
        return out
    os.makedirs(build, exist_ok=True)
    size = int(m.get("size", MAX_TEX))
    for k in KINDS:
        if m.get(k):
            rgba = load_image(os.path.join(d, m[k]), size)
        else:   # flat normal, black mask, or the plain colour
            c = [128, 128, 255] if k == "nm" else [0, 0, 0] if k == "mm" else \
                [int(round(255 * min(1.0, max(0.0, x)))) for x in m.get("colour", [0.8, 0.8, 0.8])]
            rgba = np.zeros((8, 8, 4), np.uint8)
            rgba[...] = c + [255]
        open(out[k], "wb").write(lp2tex.encode(rgba, k))
    open(kp, "w").write(key)
    return out


def ensure_material(project, name, src):
    """a file material (read_* dict) -> the project material name (made from it unless one of that name exists)"""
    old = load_material(project, name)
    d = mat_dir(project, name)
    if old:   # made before: a re-import fills in maps it lacks (the file has them now / an older import missed them)
        added = False
        for k in ("bm", "nm"):
            if src.get(k) and not old.get(k):
                fn, data = src[k]
                fn = f"{k}_{slug(os.path.splitext(fn)[0], 40)}{os.path.splitext(fn)[1].lower() or '.png'}"
                open(os.path.join(d, fn), "wb").write(data)
                old[k] = fn
                added = True
        if added:
            save_material(project, name, old)
        return name
    os.makedirs(d, exist_ok=True)
    m = {"colour": [round(float(x), 4) for x in src.get("colour", (0.8, 0.8, 0.8))]}
    for k in ("bm", "nm"):
        if src.get(k):
            fn, data = src[k]
            fn = f"{k}_{slug(os.path.splitext(fn)[0], 40)}{os.path.splitext(fn)[1].lower() or '.png'}"
            open(os.path.join(d, fn), "wb").write(data)
            m[k] = fn
    save_material(project, name, m)
    return name


def ensure_blockout(project, facing):
    """the project material blockout_<facing> (made with its blockout grid on first use) -> its name"""
    name = "blockout_" + facing
    if not load_material(project, name):
        from PIL import Image
        d = mat_dir(project, name)
        os.makedirs(d, exist_ok=True)
        colour = BLOCKOUT_FACINGS[facing]
        if facing == "window":
            Image.fromarray(window_image(colour)).save(os.path.join(d, "bm.png"))
            save_material(project, name, {"colour": list(colour), "bm": "bm.png", "grid": 1.0, "cutout": True,
                                          "shadow": False})
        else:
            Image.fromarray(blockout_image(colour)).save(os.path.join(d, "bm.png"))
            save_material(project, name, {"colour": list(colour), "bm": "bm.png", "grid": 1.0})
    return name


def split_facing(parts, windows=None, scale=100.0):
    """import.json "blockout": each part's triangles split by facing -> parts whose "mat" is @floor / @wall /
    @ceiling / @window (vertices compacted per part, the file's UVs kept: the blockout materials' grid replaces them).
    Windows: painted (windows: window_faces' seeds) or a file material named window / glass"""
    out = []
    for p in parts:
        P, T = p["P"], p["T"]
        n = np.cross(P[T[:, 1]] - P[T[:, 0]], P[T[:, 2]] - P[T[:, 0]])
        ny = n[:, 1] / np.maximum(np.linalg.norm(n, axis=1), 1e-12)
        kind = np.where(ny >= BLOCKOUT_FLOOR_Y, 0, np.where(ny <= -BLOCKOUT_FLOOR_Y, 2, 1))
        named = any(w in str(p.get("mat") or "").lower() for w in WINDOW_NAMES)
        kind = np.where(window_faces(P, T, windows, scale) | named, 3, kind)
        for k, facing in enumerate(("floor", "wall", "ceiling", "window")):
            sel = T[kind == k]
            if not len(sel):
                continue
            used, inv = np.unique(sel, return_inverse=True)
            q = dict(p, mat="@" + facing, T=inv.reshape(-1, 3))
            for key in ("P", "N", "U", "C"):
                if p.get(key) is not None:
                    q[key] = p[key][used]
            out.append(q)
    return out


def material_users(project, name):
    out = []
    for imp in list_imports(project):
        blk = imp.get("blockout") and name.startswith("blockout_") and name[9:] in BLOCKOUT_FACINGS
        if (blk or name in imp.get("slots", {}).values()) and not imp.get("missing"):   # missing: its object left the file
            out.append(imp["name"])
    return out


# ---------------------------------------------------------------- imports

def imp_dir(project, name):
    return os.path.join(project, "imports", name)


def list_imports(project):
    root = os.path.join(project, "imports")
    out = []
    for n in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        p = os.path.join(root, n, "import.json")
        if os.path.exists(p):
            out.append(dict(json.load(open(p)), name=n))
    return out


def box_tris(lo, hi):
    c = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
    quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    return c, np.array([t for a, b, cc, d in quads for t in ((a, b, cc), (a, cc, d))], np.int64)


_read_cache = {}


def read_mesh_cached(path):
    k = (path, os.path.getmtime(path))
    if k not in _read_cache:
        _read_cache.clear()
        _read_cache[k] = read_mesh(path)
    return _read_cache[k]


def split_objects(parts):
    """drawn objects -> {piece key: dict(parts in object space, M: object -> file space, instances: [M...])};
    COL_ parts go to their object's piece (in its space)"""
    pieces, order, by_node = {}, [], {}
    for p in parts:
        if is_col(p.get("obj", "")) or not len(p["T"]):
            continue
        node = p.get("node", p.get("obj", ""))
        by_node.setdefault(node, []).append(p)
    for node, ps in by_node.items():
        base = slug(obj_key(ps[0].get("obj", "")) or "mesh", 24)
        M = ps[0].get("M")
        if M is None:   # OBJ: world-space vertices; the pivot = the object's bottom centre
            allp = np.concatenate([p["P"] for p in ps])
            lo, hi = allp.min(0), allp.max(0)
            M = np.eye(4)
            M[:3, 3] = [(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2]
        key, k = base, 1
        while key in pieces:
            q = pieces[key]
            if ps[0].get("mesh") is not None and q["mesh"] == ps[0].get("mesh"):
                break   # a linked duplicate: the same piece again
            k += 1
            key = f"{base}_{k}"
        if key in pieces:
            pieces[key]["instances"].append(M)
            continue
        pieces[key] = dict(parts=[to_local(p, M) for p in ps], M=M, mesh=ps[0].get("mesh"), instances=[M],
                           name=obj_key(ps[0].get("obj", "")))
        order.append(key)
    for p in parts:
        if is_col(p.get("obj", "")) and len(p["T"]):
            want = obj_key(p["obj"][4:])
            for key in order:
                if pieces[key]["name"] == want:
                    pieces[key]["parts"].append(to_local(p, pieces[key]["M"]))
                    break
    return {k: pieces[k] for k in order}


def to_local(p, M):
    A = M[:3, :3]
    q = dict(p)
    q["P"] = (p["P"] - M[:3, 3]) @ np.linalg.inv(A).T
    if p["N"] is not None:
        q["N"] = p["N"] @ A
    if np.linalg.det(A) < 0:   # the reader flipped the winding for a mirrored node; its own space isn't mirrored
        q["T"] = p["T"][:, ::-1]
    return q


def build_import(game, project, name, log=print, d=None, mesh=None):
    """d: the piece's folder (default imports/<name>); mesh: (parts, file materials) made in code (lp2terrain.py)
    instead of reading import.json's source file"""
    d = d or imp_dir(project, name)
    cfg = json.load(open(os.path.join(d, "import.json")))
    progress(0.05, "reading " + cfg["source"])
    if mesh:
        parts, fmats = mesh
    else:
        parts, fmats = read_mesh_cached(os.path.normpath(os.path.join(d, cfg.get("source_dir", "source"), cfg["source"])))
        if cfg.get("object"):
            sp = split_objects(parts).get(cfg["object"])
            if sp is None:
                raise SystemExit(f"{cfg['source']}: no object {cfg['object']} any more")
            parts = sp["parts"]
    parts = [p for p in parts if len(p["T"])]
    # Blender objects named COL_<name>: collision only (for <name>, which then isn't collision itself)
    cols = [p for p in parts if is_col(p.get("obj", ""))]
    parts = [p for p in parts if not is_col(p.get("obj", ""))]
    covered = {obj_key(p["obj"][4:]) for p in cols}
    if not parts:
        raise SystemExit(f"{cfg['source']}: no triangles" + (" (only COL_ collision objects)" if cols else ""))
    scale = float(cfg.get("scale", 100.0))
    slots = cfg.setdefault("slots", {})
    if cfg.get("blockout"):
        parts = split_facing(parts, cfg.get("windows"), float(cfg.get("scale", 100.0)))
        slots = {"@" + f: ensure_blockout(project, f) for f in BLOCKOUT_FACINGS}
    for p in parts:
        auto = slug(p["mat"] or name)
        if p["mat"] not in slots or slots[p["mat"]] == auto:   # its own material: maps it lacks are filled in
            slots[p["mat"]] = ensure_material(project, auto, fmats.get(p["mat"], {}))
    prev = os.path.join(d, ".preview")
    if os.path.isdir(prev):
        shutil.rmtree(prev)
    out_dir = os.path.join(prev, "stage", *lp2mapc.STAGE_DIR.split("\\"))
    os.makedirs(out_dir)
    os.makedirs(os.path.join(d, "assets"), exist_ok=True)
    mat_tpl, cm_name, tb = lp2props.stage_template(game)
    open(os.path.join(prev, "online00.rModel"), "wb").write(tb)
    textures, materials, mat_index, tex_files = [cm_name], [], {}, {}
    meshes, cverts, ctris, vis = [], [], [], []
    for k, p in enumerate(parts):
        progress(0.1 + 0.6 * k / len(parts), "material " + slots[p["mat"]])
        mname = slots[p["mat"]]
        if mname not in mat_index:
            built = build_material(project, mname)
            slot = []
            for kind in KINDS:
                leaf = os.path.basename(built[kind])[:-len(".rTexture")]
                shutil.copyfile(built[kind], os.path.join(out_dir, leaf + ".rTexture"))
                full = lp2mapc.STAGE_DIR + "\\" + leaf
                textures.append(full)
                tex_files[full.lower()] = os.path.join(out_dir, leaf + ".rTexture")
                slot.append(len(textures))
            rec = bytearray(mat_tpl)
            struct.pack_into("<3I", rec, 12, *slot)
            struct.pack_into("<I", rec, 36, 1)
            if (load_material(project, mname) or {}).get("cutout"):   # alpha-tested (the stock parts' cut-out twin)
                struct.pack_into("<I", rec, 0, struct.unpack_from("<I", rec, 0)[0] | 0x4000)
            materials.append(bytes(rec))
            mat_index[mname] = len(materials) - 1
        P = p["P"] * scale
        T = p["T"]
        N = p["N"] if p["N"] is not None else lp2props.face_normals(P, T)
        U = p["U"] if p["U"] is not None else np.zeros((len(P), 2))
        C = p["C"]
        # import.json "unwrap" (the editor's Lazy unwrap): box-projected UVs whatever the material says
        grid = float(cfg.get("unwrap") or 0) or float((load_material(project, mname) or {}).get("grid") or 0)
        if grid > 0:
            if C is not None:
                C = C[T].reshape(-1, C.shape[1])
            P, T, N, U = grid_uvs(P, T, N, grid * 100)
        N = N / np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-9)
        Tg = lp2props.tangents(P, U, N, T)
        v = lp2props.stage_verts(P, N, Tg, U)
        if C is not None:
            v[:, 24:27] = np.clip(v[:, 24:27] * np.clip(C, 0, 1), 0, 255).astype(np.uint8)
        meshes.append(dict(mat=mat_index[mname], verts=v, tris=T))
        if obj_key(p.get("obj", "")) not in covered:
            ctris.append(T + len(cverts))
            cverts.extend(P.tolist())
        vis.append(P)
    by_mat = {}
    for m in meshes:
        by_mat.setdefault(m["mat"], []).append(m)
    meshes = []
    for mat, ms in by_mat.items():
        base = np.cumsum([0] + [len(m["verts"]) for m in ms[:-1]])
        meshes.append(dict(mat=mat, verts=np.concatenate([m["verts"] for m in ms]),
                           tris=np.concatenate([m["tris"] + o for m, o in zip(ms, base)])))
    model = os.path.join(out_dir, "online00.rModel")
    from lp2stage import write_stage
    write_stage(model, textures, materials, meshes)
    for p in cols:
        ctris.append(p["T"] + len(cverts))
        cverts.extend((p["P"] * scale).tolist())
    V = np.array(cverts).reshape(-1, 3)
    allv = np.concatenate(vis)
    lo, hi = allv.min(0), allv.max(0)
    coll = cfg.get("collision", "mesh")
    col_rel = None
    if coll != "none" and (coll == "box" or ctris):
        if coll == "box":
            CV, CT = box_tris(lo, hi)
        else:
            CV, CT = V, np.concatenate(ctris)
        groups = []
        for i in range(0, len(CT), 20000):   # SBC groups: at most 65535 vertices
            part = CT[i:i + 20000]
            used, inv = np.unique(part, return_inverse=True)
            groups.append(dict(verts=[tuple(x) for x in CV[used]],
                               tris=[(tuple(int(x) for x in t), 0) for t in inv.reshape(-1, 3)]))
        col_rel = "assets/collision.sbc1"
        open(os.path.join(d, col_rel), "wb").write(lp2col.write_sbc1(groups))
    elif os.path.exists(os.path.join(d, "assets", "collision.sbc1")):
        os.remove(os.path.join(d, "assets", "collision.sbc1"))
    progress(0.8, "preview")
    S = lp2pieces.read_stage(model)
    per_mesh, n = lp2pieces.atoms(S)
    stats = lp2preview.write_geo(prev, S, per_mesh, n, tex_files, 256, log)
    g = json.load(open(os.path.join(prev, "geo.json")))
    g["tree"] = [dict(name=name, atoms=list(range(n)))]   # the whole file is one piece
    stats["model_bytes"] = os.path.getsize(model)
    g["stats"] = stats
    json.dump(g, open(os.path.join(prev, "geo.json"), "w"), separators=(",", ":"))
    json.dump({"format": "lp2map", "version": 1, "info": {"name": name, "tag": "import_"},
               "base": {"stock": 0}, "stage": {"import": True},
               "collision": {"lp1_move": col_rel, "lp1_bullet": col_rel}},
              open(os.path.join(d, "project.json"), "w"), indent=1)
    cfg["size"] = [round(float(x) / 100, 2) for x in hi - lo]
    cfg["triangles"] = int(sum(len(m["tris"]) for m in meshes))
    cfg["atoms"] = int(n)
    json.dump({k: v for k, v in cfg.items() if k != "name"}, open(os.path.join(d, "import.json"), "w"), indent=1)
    progress(1.0, "done")
    log(f"{name}: {cfg['triangles']} triangles, {len(materials)} materials ({', '.join(mat_index)}), "
        f"collision {coll}{' (%d COL_ objects)' % len(cols) if cols and coll == 'mesh' else ''}, {cfg['size'][0]} x {cfg['size'][1]} x {cfg['size'][2]} m")
    return cfg


def parse_mats(items):
    out = {}
    for it in items or []:
        src, _, dst = it.partition("=")
        out[src] = dst
    return out


def copy_source(src, sd):
    if os.path.isdir(sd):
        shutil.rmtree(sd)
    for rel in source_files(src):
        dst = os.path.join(sd, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(os.path.join(os.path.dirname(src), rel), dst)


def group_path(project, name):
    return os.path.join(imp_dir(project, name), "group.json")


def import_split(a, src, name):
    d = imp_dir(a.project, name)
    if os.path.exists(os.path.join(d, "import.json")):
        raise SystemExit(f"an import named {name} exists (pick another name)")
    gp = group_path(a.project, name)
    old = json.load(open(gp)) if os.path.exists(gp) else None
    if old and not a.replace:
        raise SystemExit(f"a set named {name} exists (pick another name, or --replace)")
    copy_source(src, os.path.join(d, "source"))
    parts, fmats = read_mesh(os.path.join(d, "source", os.path.basename(src)))
    pieces = split_objects(parts)
    if not pieces:
        raise SystemExit(f"{os.path.basename(src)}: no drawn objects")
    scale = a.scale if a.scale is not None else 100.0
    old_members = dict(old.get("objects", {})) if old else {}   # object key -> import name
    taken = {x["name"] for x in list_imports(a.project)} - set(old_members.values())
    objects, layout, built = {}, [], []
    for key, pc in pieces.items():
        iname = old_members.get(key)
        if not iname:
            iname = base = slug(f"{name}_{key}", 32)
            k = 2
            while iname in taken:
                iname = slug(base, 29) + f"_{k}"
                k += 1
        taken.add(iname)
        objects[key] = iname
        md = imp_dir(a.project, iname)
        os.makedirs(md, exist_ok=True)
        cp = os.path.join(md, "import.json")
        cfg = json.load(open(cp)) if os.path.exists(cp) else {"slots": {}}
        cfg.pop("missing", None)
        cfg.update({"source": os.path.basename(src), "source_dir": f"../{name}/source", "from": src, "group": name,
                    "object": key, "scale": scale})
        if a.collision or "collision" not in cfg:
            cfg["collision"] = a.collision or "mesh"
        for s_, m in parse_mats(a.mat).items():
            cfg["slots"][s_] = slug(m)
        json.dump(cfg, open(cp, "w"), indent=1)
        for M in pc["instances"]:
            Ms = np.array(M, np.float64)
            Ms[:3, 3] *= scale / 100.0
            layout.append(dict(piece=iname, M=[round(float(x), 6) for x in Ms.reshape(-1)]))
    for i, (key, iname) in enumerate(objects.items()):
        progress(0.0, f"object {i + 1} / {len(objects)}: {key}")
        built.append(dict(build_import(a.game, a.project, iname, log=lambda *_: None), name=iname))
    gone = [v for k, v in old_members.items() if k not in objects]
    for iname in gone:   # kept (they may be placed), not rebuilt
        cp = os.path.join(imp_dir(a.project, iname), "import.json")
        if os.path.exists(cp):
            cfg = json.load(open(cp))
            cfg["missing"] = True
            json.dump(cfg, open(cp, "w"), indent=1)
            objects[next(k for k, v in old_members.items() if v == iname)] = iname
    allp = np.concatenate([(p["P"] * scale / 100.0) for p in parts if len(p["T"]) and not is_col(p.get("obj", ""))])
    lo, hi = allp.min(0), allp.max(0)
    json.dump({"source": os.path.basename(src), "from": src, "objects": objects, "layout": layout,
               "pivot": [round(float((lo[0] + hi[0]) / 2), 4), round(float(lo[1]), 4), round(float((lo[2] + hi[2]) / 2), 4)]},
              open(gp, "w"), indent=1)
    print(f"{name}: {len(built)} objects -> imports {', '.join(b['name'] for b in built)}; {len(layout)} placements"
          + (f"; no longer in the file (kept): {', '.join(gone)}" if gone else ""))
    print("@result " + json.dumps(dict(name=name, split=True, members=[b["name"] for b in built], gone=gone)))


def cmd_import(a):
    src = os.path.abspath(a.file)
    name = slug(a.name or os.path.splitext(os.path.basename(src))[0], 32)
    if a.split:
        return import_split(a, src, name)
    d = imp_dir(a.project, name)
    if os.path.exists(group_path(a.project, name)):
        raise SystemExit(f"a set named {name} exists (pick another name)")
    if os.path.exists(os.path.join(d, "import.json")) and not a.replace:
        raise SystemExit(f"an import named {name} exists (pick another name, or --replace)")
    copy_source(src, os.path.join(d, "source"))
    cfg = {"source": os.path.basename(src), "from": src, "collision": a.collision or "mesh",
           "scale": a.scale if a.scale is not None else 100.0, "slots": {}}
    old = os.path.join(d, "import.json")
    if a.replace and os.path.exists(old):   # a re-import keeps the Lazy unwrap and the Blockout
        for k in ("unwrap", "blockout"):
            if json.load(open(old)).get(k):
                cfg[k] = json.load(open(old))[k]
    for s, m in parse_mats(a.mat).items():
        cfg["slots"][s] = slug(m)
    json.dump(cfg, open(os.path.join(d, "import.json"), "w"), indent=1)
    out = build_import(a.game, a.project, name)
    print("@result " + json.dumps(dict(out, name=name)))


def cmd_rebuild(a):
    d = imp_dir(a.project, a.name)
    cfg = json.load(open(os.path.join(d, "import.json")))
    if a.collision:
        cfg["collision"] = a.collision
    if a.scale is not None:
        cfg["scale"] = a.scale
    if a.unwrap is not None:
        cfg["unwrap"] = a.unwrap
    if a.blockout is not None:
        if a.blockout:
            cfg["blockout"] = True
        else:
            cfg.pop("blockout", None)
    if a.clear_windows:
        cfg.pop("windows", None)
    for w in a.window or []:   # x,y,z,nx,ny,nz[,1 = erase]: the editor's window paint (implies blockout)
        v = [round(float(x), 4) for x in w.split(",")]
        if len(v) in (6, 7):
            cfg.setdefault("windows", []).append(v)
            cfg["blockout"] = True
    for s, m in parse_mats(a.mat).items():
        cfg.setdefault("slots", {})[s] = slug(m)
    json.dump(cfg, open(os.path.join(d, "import.json"), "w"), indent=1)
    out = build_import(a.game, a.project, a.name)
    print("@result " + json.dumps(dict(out, name=a.name)))


def cmd_material(a):
    name = slug(a.name)
    m = load_material(a.project, name) or {"colour": [0.8, 0.8, 0.8]}
    d = mat_dir(a.project, name)
    os.makedirs(d, exist_ok=True)
    for k in KINDS:
        v = getattr(a, k)
        if v is None:
            continue
        if v == "":
            m.pop(k, None)
            continue
        fn = f"{k}{os.path.splitext(v)[1].lower()}"
        if os.path.abspath(v) != os.path.abspath(os.path.join(d, fn)):
            shutil.copyfile(v, os.path.join(d, fn))
        m[k] = fn
    if a.colour:
        m["colour"] = [float(x) for x in a.colour.split(",")]
    if a.size:
        m["size"] = a.size
    if a.blockout:
        from PIL import Image
        colour = tuple(m["colour"]) if a.colour else BLOCKOUT_ORANGE
        Image.fromarray(blockout_image(colour)).save(os.path.join(d, "bm.png"))
        m["bm"] = "bm.png"
        m.setdefault("grid", 1.0)
    if a.grid is not None:
        if a.grid > 0:
            m["grid"] = a.grid
        else:
            m.pop("grid", None)
    save_material(a.project, name, m)
    build_material(a.project, name)
    users = material_users(a.project, name)
    for k, u in enumerate(users):   # their stage folders hold copies of the textures
        build_import(a.game, a.project, u)
    print(f"material {name}: built" + (f"; rebuilt {', '.join(users)}" if users else ""))
    print("@result " + json.dumps(dict(m, name=name, users=users)))


def cmd_delete(a):
    d = imp_dir(a.project, a.name)
    if not os.path.exists(os.path.join(d, "import.json")):
        raise SystemExit(f"no import {a.name}")
    cfg = json.load(open(os.path.join(d, "import.json")))
    shutil.rmtree(d)
    g = cfg.get("group")
    gp = group_path(a.project, g) if g else ""
    if gp and os.path.exists(gp):   # a set's member: drop it from the set; the last one takes the shared source
        G = json.load(open(gp))
        G["objects"] = {k: v for k, v in G.get("objects", {}).items() if v != a.name}
        G["layout"] = [x for x in G.get("layout", []) if x["piece"] != a.name]
        if G["objects"]:
            json.dump(G, open(gp, "w"), indent=1)
        else:
            shutil.rmtree(imp_dir(a.project, g))
    print(f"deleted import {a.name}")


def cmd_list(a):
    mats = []
    root = os.path.join(a.project, "materials")
    for n in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        m = load_material(a.project, n)
        if m is not None:
            mats.append(dict(m, name=n, users=material_users(a.project, n)))
    print(json.dumps({"imports": list_imports(a.project), "materials": mats}))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("import", "rebuild"):
        s = sub.add_parser(c)
        s.add_argument("--game", required=True)
        s.add_argument("project")
        s.add_argument("file" if c == "import" else "name")
        if c == "import":
            s.add_argument("--name")
            s.add_argument("--replace", action="store_true")
            s.add_argument("--split", action="store_true", help="one piece per Blender object (NAME = the set)")
        s.add_argument("--collision", choices=["mesh", "box", "none"])
        s.add_argument("--scale", type=float)
        if c == "rebuild":
            s.add_argument("--unwrap", type=float, help="box-projected UVs, metres per texture tile (0 = the file's UVs)")
            s.add_argument("--blockout", type=int, choices=[0, 1], help="1: colour by facing (floor / wall / ceiling)")
            s.add_argument("--window", action="append", help="x,y,z,nx,ny,nz[,1]: paint (1: unpaint) the flat region "
                           "there as window (editor metres, the piece's space; turns blockout on)")
            s.add_argument("--clear-windows", action="store_true", help="no painted windows")
        s.add_argument("--mat", action="append", help="SRC=MAT: the file's material SRC uses project material MAT")
    s = sub.add_parser("material")
    s.add_argument("--game", required=True)
    s.add_argument("project")
    s.add_argument("name")
    for k in KINDS:
        s.add_argument("--" + k, help="image file ('' removes it)")
    s.add_argument("--colour")
    s.add_argument("--size", type=int)
    s.add_argument("--grid", type=float, help="world-projected UVs: metres per texture tile (0 = the mesh's own UVs)")
    s.add_argument("--blockout", action="store_true", help="generate a blockout grid colour map (1 m tiles)")
    for c in ("delete", "list"):
        s = sub.add_parser(c)
        s.add_argument("project")
        if c == "delete":
            s.add_argument("name")
    a = ap.parse_args()
    {"import": cmd_import, "rebuild": cmd_rebuild, "material": cmd_material, "delete": cmd_delete,
     "list": cmd_list}[a.cmd](a)


if __name__ == "__main__":
    main()
