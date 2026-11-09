#!/usr/bin/env python3
"""A basic jeep model for the jeep test: an original light 4x4 (open tub, hood, roll cage, rear turret post, four
wheels) built from boxes and cylinders, written as a VS rModel on a stock VS's skeleton and packed into that VS's
archive as a mod override, so the VS the jeep driver moves looks like a jeep.

  lp2jeepmodel.py GAME_DIR [--vs 16] [--mod jeep] [--obj OUT.obj]

Writes GAME_DIR/Mods/<mod>/nativePC/arcLp2Xml/autoArc/uVs<NN>.arc: the stock archive with its rModel replaced
(every map's VS of that type looks like the jeep while the mod folder is there). The mesh is rigid on the root
joint, model origin on the ground under the jeep's centre, +Z forward (the jeep driver's frame: jeep_drive.cpp
writes the VS position at the ground under the body). Textures: patches of the VS's own BM texture.
--obj also writes the mesh as OBJ (metres) to look at."""
import argparse
import math
import os
import shutil
import subprocess
import sys
import tempfile

import lp2model

HERE = os.path.dirname(os.path.abspath(__file__))

# texture patches (u0, v0, u1, v1), image coordinates from the top left, on the vs16 BM atlas
PANEL = (0.59, 0.60, 0.64, 0.71)   # reddish plate
DARK = (0.68, 0.62, 0.70, 0.72)    # dark metal (frame, cage)
TREAD = (0.40, 0.29, 0.43, 0.41)   # ribbed strip (tyre tread)
HUB = (0.005, 0.56, 0.13, 0.69)    # round hub (wheel sides)
SEAT = (0.21, 0.81, 0.27, 0.86)


class Mesh:
    def __init__(self):
        self.verts, self.tris = [], []

    def quad(self, a, b, c, d, n, t, uvs):
        base = len(self.verts)
        for p, uv in zip((a, b, c, d), uvs):
            self.verts.append(dict(pos=p, normal=n, tangent=t + (1.0,), uv=(uv[0], 1.0 - uv[1]), weights=[(0, 1.0)]))
        self.tris += [(base, base + 1, base + 2), (base, base + 2, base + 3)]

    def box(self, lo, hi, patch):
        u0, v0, u1, v1 = patch
        uvs = [(u0, v1), (u1, v1), (u1, v0), (u0, v0)]
        x0, y0, z0 = lo
        x1, y1, z1 = hi
        # each face counter-clockwise seen from outside
        self.quad((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1), (0, 0, 1), (1, 0, 0), uvs)    # +Z
        self.quad((x1, y0, z0), (x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (0, 0, -1), (-1, 0, 0), uvs)  # -Z
        self.quad((x1, y0, z1), (x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (1, 0, 0), (0, 0, -1), uvs)   # +X
        self.quad((x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0), (-1, 0, 0), (0, 0, 1), uvs)   # -X
        self.quad((x0, y1, z1), (x1, y1, z1), (x1, y1, z0), (x0, y1, z0), (0, 1, 0), (1, 0, 0), uvs)    # +Y
        self.quad((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1), (0, -1, 0), (1, 0, 0), uvs)   # -Y

    def bar(self, a, b, r, patch):
        """a square bar from a to b (axis-aligned or not), r half-width"""
        d = [b[i] - a[i] for i in range(3)]
        l = math.sqrt(sum(x * x for x in d))
        f = [x / l for x in d]
        up = (0, 1, 0) if abs(f[1]) < 0.9 else (1, 0, 0)
        s = _norm(_cross(f, up))
        u = _cross(s, f)
        corners = []
        for p in (a, b):
            corners.append([tuple(p[i] + (sx * s[i] + sy * u[i]) * r for i in range(3))
                            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
        u0, v0, u1, v1 = patch
        uvs = [(u0, v1), (u1, v1), (u1, v0), (u0, v0)]
        for k in range(4):
            k2 = (k + 1) % 4
            n = _norm(tuple((corners[0][k][i] + corners[0][k2][i]) / 2 - a[i] for i in range(3)))
            self.quad(corners[0][k], corners[0][k2], corners[1][k2], corners[1][k], n, tuple(f), uvs)

    def wheel(self, c, r, w, sides=20):
        """a wheel at centre c, axis X, radius r, width w"""
        x0, x1 = c[0] - w / 2, c[0] + w / 2
        u0, v0, u1, v1 = TREAD
        for k in range(sides):
            a0, a1 = 2 * math.pi * k / sides, 2 * math.pi * (k + 1) / sides
            p = [(math.cos(a) * r, math.sin(a) * r) for a in (a0, a1)]
            n = (0.0, math.sin((a0 + a1) / 2), math.cos((a0 + a1) / 2))
            # tread
            self.quad((x1, c[1] + p[0][1], c[2] + p[0][0]), (x0, c[1] + p[0][1], c[2] + p[0][0]),
                      (x0, c[1] + p[1][1], c[2] + p[1][0]), (x1, c[1] + p[1][1], c[2] + p[1][0]),
                      (0.0, math.sin((a0 + a1) / 2), math.cos((a0 + a1) / 2)), (1, 0, 0),
                      [(u0, v0 + (v1 - v0) * k / sides), (u1, v0 + (v1 - v0) * k / sides),
                       (u1, v0 + (v1 - v0) * (k + 1) / sides), (u0, v0 + (v1 - v0) * (k + 1) / sides)])
        hu0, hv0, hu1, hv1 = HUB
        hc = ((hu0 + hu1) / 2, (hv0 + hv1) / 2)
        hr = ((hu1 - hu0) / 2, (hv1 - hv0) / 2)
        for side, x in ((1, x1), (-1, x0)):
            base = len(self.verts)
            self.verts.append(dict(pos=(x, c[1], c[2]), normal=(side, 0, 0), tangent=(0, 0, 1, 1.0),
                                   uv=(hc[0], 1.0 - hc[1]), weights=[(0, 1.0)]))
            for k in range(sides):
                a = 2 * math.pi * k / sides
                self.verts.append(dict(pos=(x, c[1] + math.sin(a) * r, c[2] + math.cos(a) * r), normal=(side, 0, 0),
                                       tangent=(0, 0, 1, 1.0),
                                       uv=(hc[0] + math.cos(a) * hr[0], 1.0 - (hc[1] - math.sin(a) * hr[1])),
                                       weights=[(0, 1.0)]))
            for k in range(sides):
                a, b = base + 1 + k, base + 1 + (k + 1) % sides
                self.tris.append((base, a, b) if side < 0 else (base, b, a))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _norm(v):
    l = math.sqrt(sum(x * x for x in v)) or 1.0
    return tuple(x / l for x in v)


def jeep_meshes():
    """(cm, origin on the ground under the centre, +Z forward, +Y up; matches jeep.h Params: 1.9 x 4.2 m body,
    wheels radius 45 at x +-85, z +-135)"""
    body, frame, tyres = Mesh(), Mesh(), Mesh()
    body.box((-88, 55, -200), (88, 100, 168), PANEL)        # tub
    body.box((-80, 100, 70), (80, 122, 200), PANEL)         # hood
    body.box((-92, 48, 196), (92, 72, 214), DARK)           # front bumper
    body.box((-92, 48, -214), (92, 68, -198), DARK)         # rear bumper
    body.box((-90, 100, -200), (90, 110, -70), PANEL)       # rear deck
    for z in (135, -135):                                   # fenders
        for sx in (-1, 1):
            body.box((min(sx * 70, sx * 108), 96, z - 58), (max(sx * 70, sx * 108), 104, z + 58), DARK)
    for x in (-45, 45):                                     # seats: cushion + back
        body.box((x - 25, 100, -5), (x + 25, 112, 45), SEAT)
        body.box((x - 25, 112, -15), (x + 25, 165, -3), SEAT)
    # windscreen frame
    frame.bar((-78, 122, 68), (-78, 182, 58), 3, DARK)
    frame.bar((78, 122, 68), (78, 182, 58), 3, DARK)
    frame.bar((-78, 182, 58), (78, 182, 58), 3, DARK)
    # roll cage over the seats
    for x in (-82, 82):
        frame.bar((x, 100, -25), (x, 205, -25), 4, DARK)
        frame.bar((x, 205, -25), (x, 182, 58), 3, DARK)
    frame.bar((-82, 205, -25), (82, 205, -25), 4, DARK)
    # rear turret post + gun
    frame.bar((0, 110, -125), (0, 185, -125), 10, DARK)
    frame.box((-14, 185, -150), (14, 210, -100), DARK)
    frame.bar((-8, 197, -100), (-8, 197, 10), 3, DARK)
    frame.bar((8, 197, -100), (8, 197, 10), 3, DARK)
    for z in (135, -135):
        for x in (-88, 88):
            tyres.wheel((x, 45, z), 45, 30)
    return [body, frame, tyres]


def write_obj(meshes, path):
    with open(path, "w") as f:
        base = 1
        for m in meshes:
            for v in m.verts:
                f.write("v %f %f %f\n" % tuple(x / 100 for x in v["pos"]))
            for t in m.tris:
                f.write("f %d %d %d\n" % tuple(base + i for i in t))
            base += len(m.verts)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("game")
    ap.add_argument("--vs", default="16", help="VS archive number (uVs<NN>.arc), default 16 (Frozen Wasteland's)")
    ap.add_argument("--mod", default="jeep")
    ap.add_argument("--mat", type=int, default=3, help="the template's material for the whole jeep")
    ap.add_argument("--group", type=int, default=0, help="the template's mesh group (0: the main body)")
    ap.add_argument("--obj")
    a = ap.parse_args()
    meshes = jeep_meshes()
    if a.obj:
        write_obj(meshes, a.obj)
    src = os.path.join(a.game, "nativePC", "arcLp2Xml", "autoArc", f"uVs{a.vs}.arc")
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([sys.executable, os.path.join(HERE, "arcx.py"), "x", src, tmp], check=True, stdout=subprocess.DEVNULL)
        model = None
        for root, _, files in os.walk(tmp):
            for n in files:
                if n.endswith(".rModel") and root.replace("\\", "/").endswith(f"model/vs/vs{a.vs}"):
                    model = os.path.join(root, n)
        if not model:
            sys.exit(f"no model/vs/vs{a.vs} rModel in {src}")
        tpl = lp2model.read_template(open(model, "rb").read())
        if tpl["mat_fmt"].get(a.mat) != lp2model.FMT_RIGID:
            sys.exit(f"material {a.mat} isn't drawn with the rigid format in this model")
        data, rep = lp2model.build_model(tpl, [], [dict(group=a.group, mat=a.mat, lodmask=lp2model.LOD_ALL,
                                                         verts=m.verts, tris=m.tris) for m in meshes], shadow=False)
        open(model, "wb").write(data)
        out_dir = os.path.join(a.game, "Mods", a.mod, "nativePC", "arcLp2Xml", "autoArc")
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, f"uVs{a.vs}.arc")
        subprocess.run([sys.executable, os.path.join(HERE, "arcx.py"), "pack", tmp, out], check=True, stdout=subprocess.DEVNULL)
    print(f"jeep model: {rep['vertices']} vertices, {rep['triangles']} triangles, {rep['bytes']} bytes -> {out}")


if __name__ == "__main__":
    main()
