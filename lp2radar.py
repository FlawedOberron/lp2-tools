#!/usr/bin/env python3
"""A project's radar (the cockpit map): one image per radar floor drawn from its navmesh, the Flash movie that shows
them, its dependency list and the floor-switch zones. lp2mapc.py puts them in the package; alone it writes PNGs.

  lp2radar.py PROJECT_DIR [--out DIR]      .preview/radar_<k>.png (or DIR), from .preview/navmesh.bin

How the game draws it (map-editor-plan.md, RADAR RE; DX9): the map clip moves by -(player x, z) cm * zoom / 100
(zoom 2.0 for area 0x700 = ONLINE_00, the base of every custom map), so one clip unit is 50 cm. The clip's movie
flash\\cockpit\\radermap\\rader_map_7_00 has one frame per floor; frame k + 1 shows floor k's image as a bitmap-filled
rectangle. mcRader.setMapType(floor) picks the frame; the floor is set only by rAreaHitLayout zones (SUCCESS 0x1000,
"RADER MAP CHANGE" = floor) and sticks until another zone fires, so the zones fill the playable space, one per floor
band and Map limits box (else the navmesh's footprint).

Our movie places each image over the navmesh's own footprint (square, + MARGIN), so any map size works: the image
is IMG px (1024 for maps over BIG_MAP), sharper for small maps than stock's fixed 256 m.

Drawing (stock style, user rules 2026-11-03): every image shows the whole navmesh dimmed, its own floor bright.
Outlines where walkable ground ends (open navmesh edges: also two sections lined up in x / z at different heights,
both filled). A ramp through a floor plane fades out over FADE past it on both floors, no outline at the plane.
Floors: project.json radar.floors (plane heights, cm): floor 0 below the first, floor k from plane k-1 to plane k.
"""
import argparse, json, math, os, struct, sys, zlib

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

UNITS_PER_CM = 2.0 / 100      # clip units per cm (zoom 2.0)
MARGIN = 1000.0               # cm around the navmesh's footprint
BIG_MAP = 40000.0             # cm: footprints wider than this get 1024 px images
FADE = 300.0                  # cm a ramp fades over past a floor plane
SS = 2                        # supersampling
DIM, BRIGHT = np.array([52, 84, 52]), np.array([86, 158, 86])
LINE_DIM, LINE_BRIGHT = np.array([74, 116, 74]), np.array([150, 236, 150])
NAME = "flash\\cockpit\\radermap\\rader_map_7_00"
IMAGE = "RADER_MAP_7_00_ONLINE00_{}_ID_HQ"           # 1-based, as stock
IMAGE_DIR = "flash\\cockpit\\mapdds\\"


def jam(s):
    return (~zlib.crc32(s.encode())) & 0xffffffff


# ---------------------------------------------------------------- data

def load_navmesh(folder):
    """.preview/navmesh.bin (lp2navmap.py) -> kept triangles (n, 3, 3) cm, or None"""
    f = os.path.join(folder, ".preview", "navmesh.bin")
    if not os.path.exists(f):
        return None
    b = open(f, "rb").read()
    n = struct.unpack_from("<I", b)[0]
    t = np.frombuffer(b, "<f4", n * 9, 4).reshape(n, 3, 3).astype(np.float64)
    keep = np.frombuffer(b, "u1", n, 4 + n * 36)
    return t[keep == 1]


def floors(p):
    return sorted(float(x) for x in ((p.get("radar") or {}).get("floors") or []))


def placement(tris):
    """the images' square footprint (x0, z0, side) cm and their size (px)"""
    lo, hi = tris.reshape(-1, 3).min(0), tris.reshape(-1, 3).max(0)
    side = max(hi[0] - lo[0], hi[2] - lo[2]) + 2 * MARGIN
    cx, cz = (lo[0] + hi[0]) / 2, (lo[2] + hi[2]) / 2
    return (cx - side / 2, cz - side / 2, side), (1024 if side > BIG_MAP else 512)


# ---------------------------------------------------------------- drawing

def _weld(tris):
    key = np.round(tris.reshape(-1, 3) * [10, 2, 10]).astype(np.int64)
    uniq, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    return tris.reshape(-1, 3)[first], inv.reshape(-1, 3)


def _edges(p):
    e = np.sort(np.concatenate([p[:, [0, 1]], p[:, [1, 2]], p[:, [2, 0]]]), axis=1)
    u, c = np.unique(e, axis=0, return_counts=True)
    return u, c


def floor_weights(v, p, lo, hi):
    """per vertex: 1 inside the band [lo, hi), fading to 0 over FADE outside it along the mesh (ramps through a
    plane); 0 for ground not joined to the band (a separate level above or below)"""
    y = v[:, 1]
    d = np.where(y < lo, lo - y, np.where(y >= hi, y - hi, 0.0))
    w = np.zeros(len(v))
    w[d == 0] = 1.0
    nb = [[] for _ in range(len(v))]
    for a, b in _edges(p)[0]:
        nb[a].append(b)
        nb[b].append(a)
    todo = list(np.flatnonzero(d == 0))
    seen = set(todo)
    while todo:
        a = todo.pop()
        for b in nb[a]:
            if b not in seen and d[b] < FADE:
                seen.add(b)
                w[b] = 1.0 - d[b] / FADE
                todo.append(b)
    return w


def _raster(pix, vals, size):
    """triangles (n, 3, 2) in pixels with per-corner values (n, 3) -> (coverage, max value) images"""
    cov = np.zeros((size, size), bool)
    out = np.zeros((size, size))
    for t, val in zip(pix, vals):
        x0, y0 = np.floor(t.min(0)).astype(int)
        x1, y1 = np.ceil(t.max(0)).astype(int)
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, size - 1), min(y1, size - 1)
        if x1 < x0 or y1 < y0:
            continue
        ys, xs = np.mgrid[y0:y1 + 1, x0:x1 + 1] + 0.5
        (ax, ay), (bx, by), (cx, cy) = t
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1e-9:
            continue
        l1 = ((by - cy) * (xs - cx) + (cx - bx) * (ys - cy)) / den
        l2 = ((cy - ay) * (xs - cx) + (ax - cx) * (ys - cy)) / den
        l3 = 1 - l1 - l2
        inside = (l1 >= -1e-6) & (l2 >= -1e-6) & (l3 >= -1e-6)
        if not inside.any():
            continue
        v = l1 * val[0] + l2 * val[1] + l3 * val[2]
        sl = (slice(y0, y1 + 1), slice(x0, x1 + 1))
        cov[sl] |= inside
        out[sl] = np.where(inside, np.maximum(out[sl], v), out[sl])
    return cov, out


def _lines(segs, vals, size, width):
    """segments (n, 2, 2) px with a value each -> max value image (0 where none)"""
    out = np.zeros((size, size))
    hit = np.zeros((size, size), bool)
    for (a, b), val in zip(segs, vals):
        x0, y0 = np.floor(np.minimum(a, b) - width).astype(int)
        x1, y1 = np.ceil(np.maximum(a, b) + width).astype(int)
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, size - 1), min(y1, size - 1)
        if x1 < x0 or y1 < y0:
            continue
        ys, xs = np.mgrid[y0:y1 + 1, x0:x1 + 1] + 0.5
        ab = b - a
        L = max(float(ab @ ab), 1e-9)
        t = np.clip(((xs - a[0]) * ab[0] + (ys - a[1]) * ab[1]) / L, 0, 1)
        dist = np.hypot(xs - (a[0] + t * ab[0]), ys - (a[1] + t * ab[1]))
        on = dist <= width / 2
        sl = (slice(y0, y1 + 1), slice(x0, x1 + 1))
        hit[sl] |= on
        out[sl] = np.where(on, np.maximum(out[sl], val), out[sl])
    return hit, out


def draw(tris, planes, place, size):
    """-> one RGBA uint8 (size, size, 4) image per floor"""
    (x0, z0, side) = place
    big = size * SS
    v, p = _weld(tris)
    pix = np.stack([(v[:, 0] - x0) / side * big, (v[:, 2] - z0) / side * big], 1)
    edges, count = _edges(p)
    open_e = edges[count == 1]
    bands = [-math.inf] + list(planes) + [math.inf]
    cov, _ = _raster(pix[p], np.zeros((len(p), 3)), big)
    images = []
    for k in range(len(planes) + 1):
        w = floor_weights(v, p, bands[k], bands[k + 1])
        _, fw = _raster(pix[p], w[p], big)
        hit, lw = _lines(pix[open_e], w[open_e].mean(1), big, 1.2 * SS)
        rgb = DIM[None, None] + (BRIGHT - DIM)[None, None] * fw[..., None]
        line = LINE_DIM[None, None] + (LINE_BRIGHT - LINE_DIM)[None, None] * lw[..., None]
        rgb = np.where(hit[..., None], line, rgb)
        a = np.where(cov | hit, 255.0, 0.0)
        img = np.concatenate([rgb, a[..., None]], -1)
        img = img.reshape(size, SS, size, SS, 4).mean((1, 3))   # supersampled down
        images.append(np.clip(img, 0, 255).astype(np.uint8))
    return images


# ---------------------------------------------------------------- game files

def texture(rgba):
    """an image -> the radar's rTexture (DXT5, one mip, format 0x2a like stock)"""
    import lp2tex
    h, w = rgba.shape[:2]
    data = lp2tex._encode_level(rgba.astype(np.float32), 23)
    head = b"TEX\0" + struct.pack("<HBB", 0x87, 0, 0) + struct.pack("<III", 2 | (1 << 4) | (1 << 9) | (w << 17),
                                                                    h | (1 << 13), 0x2a)
    return head + struct.pack("<I", 0x18) + data


class _Bits:
    def __init__(self):
        self.bits = []

    def u(self, v, n):
        self.bits += [(v >> (n - 1 - i)) & 1 for i in range(n)]

    def s(self, v, n):
        self.u(v & ((1 << n) - 1), n)

    def bytes(self):
        b = self.bits + [0] * (-len(self.bits) % 8)
        return bytes(int("".join(map(str, b[i:i + 8])), 2) for i in range(0, len(b), 8))


def _nbits(*vals):
    return max(int(abs(v)).bit_length() + 1 for v in vals) if vals else 1


def _rect(x0, x1, y0, y1):
    n = _nbits(x0, x1, y0, y1)
    b = _Bits()
    b.u(n, 5)
    for v in (x0, x1, y0, y1):
        b.s(v, n)
    return b.bytes()


def _matrix(sx, sy, tx, ty):
    b = _Bits()
    b.u(1, 1)
    n = _nbits(sx, sy)
    b.u(n, 5)
    b.s(sx, n)
    b.s(sy, n)
    b.u(0, 1)
    n = _nbits(tx, ty)
    b.u(n, 5)
    b.s(tx, n)
    b.s(ty, n)
    return b.bytes()


def _tag(code, body):
    if len(body) < 63:
        return struct.pack("<H", code << 6 | len(body)) + body
    return struct.pack("<HI", code << 6 | 63, len(body)) + body


def _shape(sid, bitmap, u0, v0, u1, v1, size):
    """a rectangle (clip units) filled with the bitmap stretched over it (stock: fill1, clockwise from top left)"""
    tw = [round(q * 20) for q in (u0, u1, v0, v1)]
    body = struct.pack("<H", sid) + _rect(tw[0], tw[1], tw[2], tw[3])
    sx = round((u1 - u0) * 20 / size * 65536)   # twips per bitmap pixel, 16.16
    sy = round((v1 - v0) * 20 / size * 65536)
    body += bytes([1, 0x41]) + struct.pack("<H", bitmap) + _matrix(sx, sy, tw[0], tw[2])
    body += bytes([0])   # no line styles
    b = _Bits()
    b.u(1, 4)            # fill bits
    b.u(0, 4)            # line bits
    b.u(0, 1)            # style change: move + fill1
    b.u(0b00101, 5)
    n = _nbits(tw[0], tw[2])
    b.u(n, 5)
    b.s(tw[0], n)
    b.s(tw[2], n)
    b.u(1, 1)
    x, y = tw[0], tw[2]
    for nx, ny in ((tw[1], tw[2]), (tw[1], tw[3]), (tw[0], tw[3]), (tw[0], tw[2])):
        dx, dy = nx - x, ny - y
        n = max(_nbits(dx, dy), 2)
        b.u(1, 1)        # edge
        b.u(1, 1)        # straight
        b.u(n - 2, 4)
        if dx and dy:
            b.u(1, 1)
            b.s(dx, n)
            b.s(dy, n)
        else:
            b.u(0, 1)
            b.u(1 if dx == 0 else 0, 1)
            b.s(dy if dx == 0 else dx, n)
        x, y = nx, ny
    b.u(0, 6)            # end
    return _tag(2, body + b.bytes())


def movie(stock, nfloors, place, size):
    """the radar movie for nfloors images over place (x0, z0, side cm), from the stock rader_map_7_00 (its header
    and the first three tags: exporter info, file attributes, background)"""
    rb = stock[8]
    nb = rb >> 3
    rect_len = (5 + 4 * nb + 7) // 8
    head_end = 8 + rect_len + 2                        # rect, frame rate
    o = head_end + 2
    first = b""
    for _ in range(3):
        h = struct.unpack_from("<H", stock, o)[0]
        ln = h & 63
        hl = 2
        if ln == 63:
            ln = struct.unpack_from("<I", stock, o + 2)[0]
            hl = 6
        first += stock[o:o + hl + ln]
        o += hl + ln
    place0 = None
    while place0 is None:                              # stock's first PlaceObject2 (matrix, colour transform)
        h = struct.unpack_from("<H", stock, o)[0]
        ln, hl = h & 63, 2
        if ln == 63:
            ln, hl = struct.unpack_from("<I", stock, o + 2)[0], 6
        if h >> 6 == 26:
            place0 = stock[o + hl:o + hl + ln]
        o += hl + ln
    x0, z0, side = place
    u0, v0 = x0 * UNITS_PER_CM, z0 * UNITS_PER_CM
    u1, v1 = (x0 + side) * UNITS_PER_CM, (z0 + side) * UNITS_PER_CM
    tags = first
    for k in range(nfloors):
        nm = IMAGE.format(k + 1)
        path = "..\\mapdds\\" + nm + ".dds"
        tags += _tag(1001, struct.pack("<HHHH", k + 1, 0x0e, size, size) + bytes([len(nm)]) + nm.encode()
                     + bytes([len(path)]) + path.encode())
        tags += _tag(56, struct.pack("<HH", 1, k + 1) + nm.encode() + b"\0")
    for k in range(nfloors):
        sid = 100 + k
        tags += _tag(12, b"\x07\x00")                  # stop
        tags += _shape(sid, k + 1, u0, v0, u1, v1, size)
        if k == 0:
            tags += _tag(26, place0[:3] + struct.pack("<H", sid) + place0[5:])
        else:
            tags += _tag(26, bytes([0x03]) + struct.pack("<HH", 1, sid))
        tags += _tag(1, b"")
    tags += _tag(0, b"")
    body = stock[8:head_end] + struct.pack("<H", nfloors) + tags
    return stock[:4] + struct.pack("<I", 8 + len(body)) + body


def archive(nfloors):
    """rader_map_7_00.rArchive: the movie's dependencies (name jamcrc, class jamcrc & 0x7fffffff)"""
    ents = [(jam((IMAGE_DIR + IMAGE.format(k + 1)).lower()), jam("rTexture") & 0x7fffffff) for k in range(nfloors)]
    ents += [(jam(NAME.lower()), jam("rFlash") & 0x7fffffff), (jam(NAME.lower()), jam("rFlashDef") & 0x7fffffff)]
    return b"ARCS" + struct.pack("<HH", 8, len(ents)) + b"".join(struct.pack("<II", a, c) for a, c in ents)


def zones(stock_hit, planes, boxes, ylo, yhi):
    """the rAreaHitLayout with one radar zone per floor band and box (corners (4, 2) x / z cm), from a stock one
    (its first radar zone is the template)"""
    import copy
    import xfsedit
    x = xfsedit.parse(stock_hit)
    L = x["root"]["mpLayoutInfoList"]
    tpl = next(z for z in L if z["SUCCESS"][0] & 0x1000)
    bands = [ylo] + list(planes) + [yhi]
    out = []
    for k in range(len(planes) + 1):
        for cs in boxes:
            z = copy.deepcopy(tpl)
            z["_id"] = len(out) + 1
            z["RADER MAP CHANGE"] = [k]
            z["p->mPosY"] = [float(bands[k])]
            z["p->mHeight"] = [float(bands[k + 1] - bands[k])]
            for i, (cx, cz) in enumerate(cs[::-1]):     # stock winding
                z[f"p->mSetPos{i}"] = [struct.pack("<4f", cx, bands[k], cz, 0.0)]
            out.append(z)
    x["root"]["mpLayoutInfoList"] = out
    return xfsedit.write(x), len(out)


def zone_boxes(p, tris):
    """the Map limits boxes' x / z corners, else the navmesh's footprint (+ MARGIN)"""
    import lp2mapc
    lim = [v for v in lp2mapc.all_parts(p) if v.get("limits")]
    if lim:
        return [lp2mapc.volume_corners(v) for v in lim]
    lo, hi = tris.reshape(-1, 3).min(0) - MARGIN, tris.reshape(-1, 3).max(0) + MARGIN
    return [[(lo[0], lo[2]), (hi[0], lo[2]), (hi[0], hi[2]), (lo[0], hi[2])]]


def build(folder, p, log=print):
    """-> dict(images=[rgba], place, size, planes) or None without a navmesh"""
    tris = load_navmesh(folder)
    if tris is None or not len(tris):
        return None
    planes = floors(p)
    place, size = placement(tris)
    images = draw(tris, planes, place, size)
    log(f"radar: {len(images)} floor{'s' if len(images) > 1 else ''}, {size} px over {place[2] / 100:.0f} m")
    return dict(images=images, place=place, size=size, planes=planes, tris=tris)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("project")
    ap.add_argument("--out")
    a = ap.parse_args()
    folder = os.path.abspath(a.project)
    p = json.load(open(os.path.join(folder, "project.json")))
    r = build(folder, p)
    if r is None:
        raise SystemExit("no navmesh: build one first (Navmesh window)")
    from PIL import Image
    out = a.out or os.path.join(folder, ".preview")
    os.makedirs(out, exist_ok=True)
    files = []
    for k, img in enumerate(r["images"]):
        f = os.path.join(out, f"radar_{k}.png")
        Image.fromarray(img).save(f)
        files.append(f)
    print("@result " + json.dumps({"images": files, "size": r["size"], "side_m": r["place"][2] / 100}))


if __name__ == "__main__":
    sys.exit(main())
