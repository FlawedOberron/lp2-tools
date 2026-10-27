#!/usr/bin/env python3
"""Map Editor level geometry: a built stage rModel split into pieces, and the editor's edits applied to it.

  lp2pieces.py info STAGE.rModel                       atoms and default pieces
  lp2pieces.py apply STAGE.rModel GEOMETRY.json OUT    the stage with the edits (tests; lp2mapc.py does this)

Atoms: the stage's triangles joined by shared corners (positions welded to 1 cm), across materials; numbered
by their first triangle in mesh order, so the same stage always gives the same atom ids. Atoms are what edits
address. Default pieces (what the editor shows as level geometry objects): atoms whose boxes, grown by
0.5 m, touch, leaving out atoms over 40 m across (terrain), which stay pieces of their own; each splits
(Ungroup) into the groups whose boxes touch without growing, then into atoms.

GEOMETRY.json (the project's geometry file, written by the editor):
  "xf":     {"<atom>": [12 floats]}    3 x 4 row-major matrix, cm: new = M[:, :3] @ old + M[:, 3]
  "hidden": [atoms]                    left out of the built stage and its collision
  "copies": [{"atom": a, "m": [12]}]   extra copies of an atom's original geometry (duplicates, prefabs);
            with "map": "lp1/s900" the atom is another map's, from the editor's asset library (lp2library.py:
            its built stage, materials and textures are merged in, its collision copied the same way)
  "walls_hidden": [k]                  collision-only walls (collision_owners) left out: LP1's invisible boundaries
  "tree":   [{"name", "atoms" | "children", "copies"}]  the editor's grouping; a node with "mesh_collision": true
            (and everything under it) gets collision made from its visible triangles instead of the map's
Collision (lp2col.py groups, LP1 SBC1 read) follows: each collision triangle goes with the visual atom nearest
its centre (within 4 m); triangles of moved atoms are moved, of hidden ones dropped, of copied ones copied.
"""
import argparse, json, os, shutil, struct, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mod2obj  # noqa: E402

STAGE_FMT, STRIDE = 0x49B4F022, 28
BIG, PAD = 4000.0, 50.0  # cm: atoms wider than BIG stay alone; boxes grown by PAD join
NEAR = 400.0  # cm: collision triangle -> atom search radius


def progress(f, text=""):
    print(f"@progress {f:.3f} {text}", flush=True)


def read_stage(path):
    """-> dict(head, textures [names], materials [160 B], meshes [dict(mat, v (n, 28) u8, tris (k, 3))])"""
    b = open(path, "rb").read()
    M = mod2obj.read_model(b)
    ntex, o_tex = struct.unpack_from("<I", b, 0x1C)[0], struct.unpack_from("<I", b, 0x2C)[0]
    nmat = struct.unpack_from("<H", b, 0x0A)[0]
    textures = [b[o_tex + i * 64:o_tex + i * 64 + 64].split(b"\0")[0].decode() for i in range(ntex)]
    o_mat = o_tex + ntex * 64
    materials = [b[o_mat + i * 160:o_mat + i * 160 + 160] for i in range(nmat)]
    meshes = []
    for m in M["meshes"]:
        if m["fmt"] != STAGE_FMT or not m["icount"]:
            continue
        idx = np.frombuffer(b, "<u2", m["icount"], M["ib"] + m["istart"] * 2).astype(np.int64)
        used, inv = np.unique(idx, return_inverse=True)
        raw = np.frombuffer(b, np.uint8, (int(used.max()) + m["vbase"] + 1) * STRIDE, M["vb"] + m["voff"])
        meshes.append(dict(mat=m["mat"], v=raw.reshape(-1, STRIDE)[used + m["vbase"]].copy(), tris=inv.reshape(-1, 3)))
    return dict(textures=textures, materials=materials, meshes=meshes)


def positions(v):
    return v[:, :12].copy().view("<f4").reshape(-1, 3).astype(np.float64)


def atoms(S):
    """Per mesh: atom id of each triangle (list of arrays); and the atom count."""
    pos = np.concatenate([positions(m["v"]) for m in S["meshes"]])
    base = np.cumsum([0] + [len(m["v"]) for m in S["meshes"]])
    tris = np.concatenate([m["tris"] + base[k] for k, m in enumerate(S["meshes"])])
    _, wid = np.unique(np.round(pos).astype(np.int64), axis=0, return_inverse=True)
    T = wid.ravel()[tris]
    lab = np.arange(T.max() + 1)
    e = np.concatenate([T[:, [0, 1]], T[:, [1, 2]]])
    while True:  # label propagation with pointer jumping
        lo = np.minimum(lab[e[:, 0]], lab[e[:, 1]])
        np.minimum.at(lab, e[:, 0], lo)
        np.minimum.at(lab, e[:, 1], lo)
        nxt = lab[lab]
        while (nxt != lab).any():
            lab, nxt = nxt, nxt[nxt]
        if (lab[e[:, 0]] == lab[e[:, 1]]).all():
            break
    tl = lab[T[:, 0]]
    first = {}
    for x in tl.tolist():  # number by first triangle
        first.setdefault(x, len(first))
    keys = np.array(list(first.keys()))
    order = np.empty(lab.max() + 1, np.int64)
    order[keys] = np.arange(len(keys))
    ta = order[tl]
    counts = np.cumsum([0] + [len(m["tris"]) for m in S["meshes"]])
    return [ta[counts[k]:counts[k + 1]] for k in range(len(S["meshes"]))], len(keys)


def atom_boxes(S, per_mesh, n):
    lo, hi = np.full((n, 3), np.inf), np.full((n, 3), -np.inf)
    cnt = np.zeros(n, np.int64)
    for m, ta in zip(S["meshes"], per_mesh):
        tp = positions(m["v"])[m["tris"]]
        np.minimum.at(lo, ta, tp.min(1))
        np.maximum.at(hi, ta, tp.max(1))
        np.add.at(cnt, ta, 1)
    return lo, hi, cnt


def clusters(lo, hi, pad, atoms_):
    """Atoms (of the given ids) whose boxes grown by pad touch -> [[atoms]]; atoms over BIG across stay alone."""
    atoms_ = np.asarray(atoms_)
    par = list(range(len(atoms_)))

    def find(i):
        while par[i] != i:
            par[i] = par[par[i]]
            i = par[i]
        return i

    small = np.where(np.linalg.norm(hi[atoms_] - lo[atoms_], axis=1) < BIG)[0]
    L, H = lo[atoms_[small]] - pad, hi[atoms_[small]] + pad
    for s in range(0, len(small), 512):
        hit = np.all((L[s:s + 512, None] <= H[None]) & (L[None] <= H[s:s + 512, None]), axis=2)
        for i, j in zip(*np.nonzero(hit)):
            a, b = find(int(small[s + i])), find(int(small[j]))
            if a != b:
                par[max(a, b)] = min(a, b)
    groups = {}
    for i in range(len(atoms_)):
        groups.setdefault(find(i), []).append(int(atoms_[i]))
    return list(groups.values())


def piece_name(S, per_mesh, group, counter):
    """Name from the piece's most used colour map, e.g. 'rock01 2'."""
    mats = {}
    gs = set(group)
    for m, ta in zip(S["meshes"], per_mesh):
        k = int(np.isin(ta, list(gs)).sum())
        if k:
            mats[m["mat"]] = mats.get(m["mat"], 0) + k
    mat = max(mats, key=mats.get)
    slot = struct.unpack_from("<I", S["materials"][mat], 12)[0]
    t = S["textures"][slot - 1].split("\\")[-1] if 0 < slot <= len(S["textures"]) else "piece"
    t = t[4:] if t.startswith("lp1_") else t
    t = t[:-3] if t.lower().endswith("_bm") else t
    counter[t] = counter.get(t, 0) + 1
    return t if counter[t] == 1 else f"{t} {counter[t]}"


def default_tree(S, per_mesh, n):
    """Pieces: atoms whose boxes grown by PAD touch; inside, the touching groups (no growth); then atoms.
    Each node: dict(name, atoms) for a group of atoms, or dict(name, children)."""
    lo, hi, cnt = atom_boxes(S, per_mesh, n)
    tris = lambda g: int(cnt[g].sum())
    counter = {}
    tree = []
    for k, g in enumerate(sorted(clusters(lo, hi, PAD, range(n)), key=lambda g: -tris(g))):
        name = "terrain" if k == 0 else piece_name(S, per_mesh, g, counter)
        inner = sorted(clusters(lo, hi, 0.0, g), key=lambda g: -tris(g))
        if len(inner) == 1:
            tree.append(dict(name=name, atoms=sorted(g)))
        else:
            tree.append(dict(name=name, children=[dict(name=f"{name}.{i + 1}", atoms=sorted(x)) for i, x in enumerate(inner)]))
    return tree


# ---------------------------------------------------------------- edits

def matrix(m):
    return np.asarray(m, np.float64).reshape(3, 4)


def u8n(n):
    n = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
    return np.clip(np.round(n * 127 + 127), 0, 255).astype(np.uint8)


def transform_verts(v, M):
    """Stage vertices (n, 28) through a 3 x 4 matrix: position, normal (inverse transpose), tangent."""
    out = v.copy()
    R, t = M[:, :3], M[:, 3]
    p = positions(v) @ R.T + t
    out[:, :12] = p.astype("<f4").view(np.uint8).reshape(-1, 12)
    n = (v[:, 12:15].astype(np.float64) - 127) / 127
    tg = (v[:, 16:19].astype(np.float64) - 127) / 127
    out[:, 12:15] = u8n(n @ np.linalg.inv(R))  # (R^-T n) as rows
    out[:, 16:19] = u8n(tg @ R.T)
    return out  # a mirroring matrix also needs the winding reversed (the callers do)


def edited(geo):
    return bool(geo and (geo.get("xf") or geo.get("hidden") or geo.get("copies") or geo.get("walls_hidden")
                         or mesh_collision(geo)[0] or mesh_collision(geo)[1]))


WALL = -1000000   # owner of collision-only wall k: WALL - k


def collision_owners(groups, S, per_mesh):
    """per group, per triangle: the stage atom nearest its centre (within NEAR), or WALL - k for collision-only
    wall k: triangles with no visible geometry near (invisible boundaries), joined by shared corners (welded to
    1 cm) and numbered by their first triangle, so the same map always gives the same wall ids."""
    samples, ids = atom_samples(S, per_mesh)
    own, loose = [], []
    for gi, g in enumerate(groups):
        if not g["tris"]:
            own.append(np.zeros(0, np.int64))
            continue
        V = np.asarray(g["verts"], np.float64).reshape(-1, 3)
        tri = np.array([t for t, _ in g["tris"]], np.int64)
        o = nearest_atom(V[tri].mean(1), samples, ids)
        own.append(o)
        loose += [(gi, int(k)) for k in np.nonzero(o == -1)[0]]
    parent = list(range(len(loose)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    corner = {}
    for i, (gi, k) in enumerate(loose):
        V = groups[gi]["verts"]
        for vi in groups[gi]["tris"][k][0]:
            key = tuple(int(round(c)) for c in V[vi])
            j = corner.setdefault(key, i)
            if j != i:
                parent[find(i)] = find(j)
    wall = {}
    for i, (gi, k) in enumerate(loose):   # loose is in (group, triangle) order: walls numbered by first triangle
        own[gi][k] = WALL - wall.setdefault(find(i), len(wall))
    return own


def mesh_collision(geo):
    """(atoms, copy indexes) under tree nodes marked "mesh_collision": collision from their visible triangles"""
    atoms, copies = set(), set()

    def walk(t, on):
        on = on or bool(t.get("mesh_collision"))
        for c in t.get("children", []):
            walk(c, on)
        if on:
            atoms.update(int(a) for a in t.get("atoms", []))
            copies.update(int(k) for k in t.get("copies", []))
    for t in (geo or {}).get("tree") or []:
        walk(t, False)
    return atoms, copies


MESH_SURFACE = 0x3FFFFF00   # LP1's plain surface (lp2col: the template's plain one)


def mesh_groups(S, per_mesh, atoms, M=None, own=-1):
    """the atoms' stage triangles as collision groups (through 3 x 4 matrix M, cm), each triangle owned by own
    (default: its atom); at most 65535 vertices per group"""
    out, verts, tris, owner, vmap = [], [], [], [], {}
    for m, ta in zip(S["meshes"], per_mesh):
        sel = np.nonzero(np.isin(ta, list(atoms)))[0]
        if not len(sel):
            continue
        P = positions(m["v"]).astype(np.float64)
        if M is not None:
            P = P @ M[:, :3].T + M[:, 3]
        flip = M is not None and np.linalg.det(M[:, :3]) < 0
        for k in sel:
            if len(verts) > 0xFFFF - 3:
                out.append(dict(verts=verts, tris=tris, own=owner))
                verts, tris, owner, vmap = [], [], [], {}
            ids = []
            for i in m["tris"][k]:
                key = (id(m), int(i))
                if key not in vmap:
                    vmap[key] = len(verts)
                    verts.append(tuple(P[i]))
                ids.append(vmap[key])
            tris.append((tuple(ids[::-1]) if flip else tuple(ids), MESH_SURFACE))
            owner.append(int(ta[k]) if own == -1 else own)
    if tris:
        out.append(dict(verts=verts, tris=tris, own=owner))
    return out


def apply_stage(S, per_mesh, geo):
    """-> new meshes [dict(mat, verts (n, 28), tris)]"""
    xf = {int(k): matrix(v) for k, v in (geo.get("xf") or {}).items()}
    hidden = set(int(a) for a in geo.get("hidden") or [])
    copies = geo.get("copies") or []
    out = []
    for m, ta in zip(S["meshes"], per_mesh):
        v, tris = m["v"].copy(), m["tris"]
        keep = ~np.isin(ta, list(hidden)) if hidden else np.ones(len(tris), bool)
        flip = np.zeros(len(tris), bool)
        for a, M in xf.items():
            sel = ta == a
            if not sel.any():
                continue
            vi = np.unique(tris[sel])
            v[vi] = transform_verts(m["v"][vi], M)
            if np.linalg.det(M[:, :3]) < 0:
                flip |= sel
        t = tris.copy()
        t[flip] = t[flip][:, ::-1]
        out.append(dict(mat=m["mat"], verts=v, tris=t[keep]))
    return out + copy_meshes(S, per_mesh, [c for c in copies if not c.get("map")])


TEX_SLOTS = (3, 4, 5, 9)   # a stage material's u32 texture slots (1-based): colour, normal, mask, environment cube


def prune(textures, materials, meshes, tex_dir, log=print):
    """drop what no remaining triangle uses (hidden pieces' meshes, their materials, then textures; the unused
    textures' files in tex_dir are deleted, so the package and the game's memory don't carry them)
    -> (textures, materials, meshes)"""
    meshes = [m for m in meshes if len(m["tris"])]
    used = sorted({m["mat"] for m in meshes})
    mmap = {old: new for new, old in enumerate(used)}
    mats = [bytearray(materials[i]) for i in used]
    tused = sorted({struct.unpack_from("<I", r, 4 * k)[0] for r in mats for k in TEX_SLOTS} - {0})
    tmap = {old: new + 1 for new, old in enumerate(tused)}   # 1-based slots, 0 = none
    for r in mats:
        for k in TEX_SLOTS:
            struct.pack_into("<I", r, 4 * k, tmap.get(struct.unpack_from("<I", r, 4 * k)[0], 0))
    for m in meshes:
        m["mat"] = mmap[m["mat"]]
    keep = [textures[t - 1] for t in tused]
    dropped = [t for t in textures if t not in set(keep)]
    for t in dropped:
        p = os.path.join(tex_dir, t.split("\\")[-1] + ".rTexture")
        if os.path.exists(p):
            os.remove(p)
    if dropped or len(used) < len(materials):
        log(f"  unused: {len(materials) - len(used)} materials, {len(dropped)} textures dropped")
    return keep, [bytes(r) for r in mats], meshes


def copy_meshes(S, per_mesh, copies):
    """the copied atoms' triangles, transformed: [dict(mat, verts, tris)]; copies with the same matrix (one placed
    piece's atoms) share a mesh per source mesh, so placed pieces don't add a mesh per atom"""
    out = []
    by_m = {}
    for c in copies:
        by_m.setdefault(tuple(c["m"]), dict(m=c["m"], atoms=[]))["atoms"].append(int(c["atom"]))
    for m, ta in zip(S["meshes"], per_mesh):
        for c in by_m.values():
            sel = np.isin(ta, c["atoms"])
            if not sel.any():
                continue
            M = matrix(c["m"])
            vi, inv = np.unique(m["tris"][sel], return_inverse=True)
            ct = inv.reshape(-1, 3)
            if np.linalg.det(M[:, :3]) < 0:
                ct = ct[:, ::-1]
            out.append(dict(mat=m["mat"], verts=transform_verts(m["v"][vi], M), tris=ct))
    return out


def foreign_copies(geo):
    """{library map ("lp1/s900"): [copy]}: copies of pieces from other maps (the editor's asset library)"""
    out = {}
    for c in geo.get("copies") or []:
        if c.get("map"):
            out.setdefault(c["map"], []).append(c)
    return out


def map_folder(lib, rel, project=None):
    """a library map's folder: LIB/<rel>, or PROJECT/<rest> for "@project/<rest>" (the project's own imported
    meshes, lp2mesh.py)"""
    if rel.startswith("@project/"):
        if not project:
            raise SystemExit(f"{rel}: a project's own map, but no project folder given")
        return os.path.join(project, *rel[len("@project/"):].split("/"))
    if not lib:
        raise SystemExit(f"{rel}: pieces from the asset library, but no library given (--library)")
    return os.path.join(lib, *rel.split("/"))


def library_stage(lib, rel, project=None):
    """a library map's built stage model (lp2library.py: LIB/<rel>/.preview/stage/...) and its stage folder"""
    stage = os.path.join(map_folder(lib, rel, project), ".preview", "stage")
    for d, _, fs in os.walk(stage):
        if "online00.rModel" in fs:
            return os.path.join(d, "online00.rModel"), d
    raise SystemExit(f"{rel}: not in the asset library {lib} (Browser > Get assets)")


def merge_foreign(S, meshes, geo, lib, tex_dir, log=print, project=None):
    """append other maps' copied pieces to the stage: their meshes, materials (texture slots renumbered) and
    textures (copied into tex_dir unless a texture of that name is there). -> (textures, materials, meshes)"""
    textures, materials = list(S["textures"]), list(S["materials"])
    have = {t.lower(): i for i, t in enumerate(textures)}
    for rel, copies in foreign_copies(geo).items():
        model, src_dir = library_stage(lib, rel, project)
        F = read_stage(model)
        fpm, _ = atoms(F)
        fm = copy_meshes(F, fpm, copies)
        tmap, mmap = {}, {}
        for m in fm:
            if m["mat"] not in mmap:
                rec = bytearray(F["materials"][m["mat"]])
                for k in TEX_SLOTS:
                    t = struct.unpack_from("<I", rec, 4 * k)[0]
                    if t:
                        if t not in tmap:
                            name = F["textures"][t - 1]
                            if name.lower() not in have:
                                have[name.lower()] = len(textures)
                                textures.append(name)
                                leaf = name.split("\\")[-1] + ".rTexture"
                                srcf = os.path.join(src_dir, leaf)
                                if os.path.exists(srcf):
                                    shutil.copyfile(srcf, os.path.join(tex_dir, leaf))
                            tmap[t] = have[name.lower()] + 1
                        struct.pack_into("<I", rec, 4 * k, tmap[t])
                mmap[m["mat"]] = len(materials)
                materials.append(bytes(rec))
            m["mat"] = mmap[m["mat"]]
        meshes = meshes + fm
        log(f"  {rel}: {len(copies)} pieces copied, {len(tmap)} textures")
    return textures, materials, meshes


def foreign_collision(lib, geo, key, project=None):
    """the other maps' copied pieces' collision (key lp1_move / lp1_bullet in their library projects): extra groups"""
    import lp2col
    extra = []
    for rel, copies in foreign_copies(geo).items():
        folder = map_folder(lib, rel, project)
        p = json.load(open(os.path.join(folder, "project.json")))
        if not p["collision"].get(key):   # an imported mesh with no collision
            continue
        groups = lp2col.read_sbc1(open(os.path.join(folder, p["collision"][key]), "rb").read())
        F = read_stage(library_stage(lib, rel, project)[0])
        fpm, n = atoms(F)
        everything = geo.get("copies") or []
        own = [dict({k: v for k, v in c.items() if k != "map"}, _i=next(i for i, e in enumerate(everything) if e is c))
               for c in copies]   # apply_collision skips map copies; _i: the index in the geometry's list
        out, _ = apply_collision(groups, F, fpm, n, {"copies": own})
        extra += out[len(groups):]   # only the copies (apply_collision returns the groups, then the copies)
    return extra


def atom_samples(S, per_mesh, region=None):
    """Points on the stage's surface (corners and centres of triangles) with their atom ids."""
    pts, ids = [], []
    for m, ta in zip(S["meshes"], per_mesh):
        tp = positions(m["v"])[m["tris"]]
        p = np.concatenate([tp.mean(1), tp[:, 0], tp[:, 1], tp[:, 2]])
        a = np.tile(ta, 4)
        if region is not None:
            sel = np.all((p >= region[0]) & (p <= region[1]), axis=1)
            p, a = p[sel], a[sel]
        pts.append(p)
        ids.append(a)
    return np.concatenate(pts), np.concatenate(ids)


def nearest_atom(points, samples, sample_ids):
    """Atom of the nearest sample within NEAR of each point, else -1 (grid of NEAR cells, 27 neighbours)."""
    res = np.full(len(points), -1, np.int64)
    best = np.full(len(points), NEAR * NEAR)
    cell = lambda p: np.floor(p / NEAR).astype(np.int64)
    sc = cell(samples)
    grid = {}
    order = np.lexsort(sc.T[::-1])
    keys, start = np.unique(sc[order], axis=0, return_index=True)
    ends = np.append(start[1:], len(order))
    for k, s, e in zip(map(tuple, keys), start, ends):
        grid[k] = order[s:e]
    pc = cell(points)
    by_cell = {}
    for i, k in enumerate(map(tuple, pc)):
        by_cell.setdefault(k, []).append(i)
    for k, idx in by_cell.items():
        cand = [grid[n] for n in ((k[0] + dx, k[1] + dy, k[2] + dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                                  for dz in (-1, 0, 1)) if n in grid]
        if not cand:
            continue
        cand = np.concatenate(cand)
        idx = np.array(idx)
        d = ((points[idx, None] - samples[None, cand]) ** 2).sum(2)
        j = d.argmin(1)
        dm = d[np.arange(len(idx)), j]
        ok = dm < best[idx]
        res[idx[ok]] = sample_ids[cand[j[ok]]]
        best[idx[ok]] = dm[ok]
    return res


def apply_collision(groups, S, per_mesh, n, geo):
    """lp2col.py groups (LP1 read) -> groups with the edits; and (moved, dropped, copied) triangle counts.
    Each returned group has "own": per triangle its atom, WALL - k for collision-only wall k (collision_owners),
    or -2 - k for copy k of geo["copies"] (a copy's "_i" when the caller renumbered them)."""
    xf = {int(k): matrix(v) for k, v in (geo.get("xf") or {}).items()}
    hidden = set(int(a) for a in geo.get("hidden") or [])
    copies = [dict(c, _i=c.get("_i", i)) for i, c in enumerate(geo.get("copies") or []) if not c.get("map")]
    mesh_atoms, mesh_copies = mesh_collision(geo)
    walls_gone = {WALL - int(k) for k in geo.get("walls_hidden") or []}
    owners = collision_owners(groups, S, per_mesh)
    moved = dropped = copied = 0
    out, extra = [], []
    for g, own in zip(groups, owners):
        V = np.asarray(g["verts"], np.float64).reshape(-1, 3)
        if not g["tris"]:
            out.append(dict(g, own=[]))
            continue
        verts = [tuple(x) for x in g["verts"]]
        vnew, keep, kept_own = {}, [], []
        for k, ((a, b, c), f) in enumerate(g["tris"]):
            o = int(own[k])
            if o in hidden or o in mesh_atoms or o in walls_gone:
                dropped += 1
                continue
            if o in xf:  # its own transformed corners (a corner may be shared with an unmoved triangle)
                M = xf[o]
                ids_ = []
                for i in (a, b, c):
                    key = (i, o)
                    if key not in vnew:
                        vnew[key] = len(verts)
                        verts.append(tuple(M[:, :3] @ V[i] + M[:, 3]))
                    ids_.append(vnew[key])
                tt = tuple(ids_) if np.linalg.det(M[:, :3]) > 0 else tuple(ids_[::-1])
                keep.append((tt, f))
                kept_own.append(o)
                moved += 1
            else:
                keep.append(((a, b, c), f))
                kept_own.append(o)
        out.append(dict(g, verts=verts, tris=keep, own=kept_own))
        for cp in copies:
            if cp["_i"] in mesh_copies:
                continue
            sel = np.nonzero(own == int(cp["atom"]))[0]
            if not len(sel):
                continue
            M = matrix(cp["m"])
            used = sorted({i for k in sel for i in g["tris"][k][0]})
            rm = {i: j for j, i in enumerate(used)}
            cv = [tuple(M[:, :3] @ V[i] + M[:, 3]) for i in used]
            ct = []
            for k in sel:
                (a, b, c), f = g["tris"][k]
                tt = (rm[a], rm[b], rm[c])
                ct.append((tt if np.linalg.det(M[:, :3]) > 0 else tt[::-1], f))
            extra.append(dict(g, verts=cv, tris=ct, own=[-2 - cp["_i"]] * len(ct)))
            copied += len(ct)
    # collision from the visible triangles: the marked atoms where the editor put them, and marked copies
    mesh = mesh_groups(S, per_mesh, mesh_atoms - hidden - set(xf)) if mesh_atoms - hidden - set(xf) else []
    for a in sorted((mesh_atoms - hidden) & set(xf)):
        mesh += mesh_groups(S, per_mesh, {a}, xf[a])
    for cp in copies:
        if cp["_i"] in mesh_copies:
            mesh += mesh_groups(S, per_mesh, {int(cp["atom"])}, matrix(cp["m"]), -2 - cp["_i"])
    extra += mesh
    copied += sum(len(g["tris"]) for g in mesh)
    for g in out:
        if len(g["verts"]) > 0xFFFF:  # moved corners added past the group's limit: split off the moved part
            raise SystemExit("collision group over 65535 vertices after moving geometry")
    return out + extra, (moved, dropped, copied)


def load_geometry(path):
    return json.load(open(path)) if path and os.path.exists(path) else {}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("info")
    i.add_argument("model")
    a_ = sub.add_parser("apply")
    a_.add_argument("model")
    a_.add_argument("geometry")
    a_.add_argument("out")
    a = ap.parse_args()
    S = read_stage(a.model)
    per_mesh, n = atoms(S)
    if a.cmd == "info":
        tree = default_tree(S, per_mesh, n)
        print(f"{n} atoms, {len(tree)} pieces")
        for t in tree[:12]:
            print(f"  {t['name']}: {len(t.get('children', []))} parts, {len(t.get('atoms', []))} atoms")
    else:
        import lp2stage
        meshes = apply_stage(S, per_mesh, load_geometry(a.geometry))
        lp2stage.write_stage(a.out, S["textures"], S["materials"], meshes)


if __name__ == "__main__":
    main()
