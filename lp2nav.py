#!/usr/bin/env python3
"""LP2 AI navigation: read / write rAINavigationMeshList (LNV) and rAIWayPoint (WAY).

  lp2nav.py info FILE                  summary of a navmesh or waypoint file
  lp2nav.py obj FILE.rAINavigationMeshList OUT.obj [WAY.rAIWayPoint]
                                       mesh (one object per area) + links + waypoints, LP2 units, Y up
  lp2nav.py roundtrip FILE             parse and rewrite, check the bytes match

Bot matches (training's AI Enemy Battle, aArea_TUTOREAL_51-75) load both from
tool\\AI\\NaviMesh\\Train_NN\\: List_Train_NN.rAINavigationMeshList and Way_Train_NN.rAIWayPoint.
Online areas have neither. Little endian; str = u32 length + chars + NUL. Readers: DX9 LNV 0x6ddea0
(mesh 0x7548a0, areas 0x759940), WAY 0x6dc6d0.

LNV, version 9:
  'LNV\\0' u32 9, u8 meshes, per mesh:
    str path, str name, u16, u8, u8, u8 k + k bytes, u32 n + n vec3          (stock: 0, 0, 255, -, 0)
    str name, u32 verts, u32 polys, u32 extra, verts x vec3
    polys x {u32 id, u32 n + n u32 flags (stock: 1, 0 / 0x400 / 0x800 / 0x40000 / 0x2000000),
             u8, vec3, f32 (stock 0, (0,0,1), 0), u8 n + n u32 (stock none),
             u32 n + n u32 vertex ids (3), u32 n + n x {u32 poly, u32 0, u32 edge 0-2, f32 cost}}
      polys are sorted by area; a link crosses edge e (vertex e -> e+1) into the other polygon.
    u16 areas, per area:
      u16 id, str name ("root", "area_aabb"), u32, u32 n shapes + n x {u8 type; 0: vec3 min, vec3 max;
        1: vec3 + 4 x vec4; 2: f32 radius + vec3}, u16 first poly, u16 end poly, u16 parent (root 0xffff),
      u8 n + n bytes children, u8 n + n bytes neighbours
    u16, u16 (stock: leaf areas, ?), u32 links, u32 polys, u32 vertex ids (3 x polys), extra x {u32, 32 bytes}
    quadtree: u8 depth, u32 cells (sum of 4^i), vec4 min, vec4 max, cells x {u32 n + n x (u32 poly, u32)}

WAY, version 16:
  'WAY\\0' u32 16, u32 n, n x {u32 id, vec3, u32 na, u32 nb, na u32 (stock 1 value: 0xffffffff in the
    open, others with a repeated u16), nb u32, nb u32, u8 type (1: + 16 bytes, 2: + 80 bytes)}
  u32 0, u32 n, quadtree as above but the box is 2 x vec3 (max, min) after u8 depth, u32 cells.
"""
import struct
import sys


class Reader:
    def __init__(self, data):
        self.b, self.o = data, 0

    def take(self, fmt):
        v = struct.unpack_from('<' + fmt, self.b, self.o)
        self.o += struct.calcsize('<' + fmt)
        return v if len(v) > 1 else v[0]

    def many(self, fmt, n):
        return [self.take(fmt) for _ in range(n)]

    def raw(self, n):
        v = self.b[self.o:self.o + n]
        self.o += n
        return v

    def str(self):
        n = self.take('I')
        v = self.raw(n)
        self.o += 1
        return v.decode('latin-1')


class Writer:
    def __init__(self):
        self.parts = []

    def put(self, fmt, *v):
        self.parts.append(struct.pack('<' + fmt, *v))

    def raw(self, b):
        self.parts.append(bytes(b))

    def str(self, s):
        b = s.encode('latin-1')
        self.put('I', len(b))
        self.raw(b + b'\0')

    def bytes(self):
        return b''.join(self.parts)


def read_tree(r, box):
    depth = r.take('B')
    n = r.take('I')
    bbox = r.take(box)
    cells = [r.many('II', r.take('I')) for _ in range(n)]
    return {'depth': depth, 'box': list(bbox), 'cells': cells}


def write_tree(w, t, box):
    w.put('B', t['depth'])
    w.put('I', len(t['cells']))
    w.put(box, *t['box'])
    for c in t['cells']:
        w.put('I', len(c))
        for e in c:
            w.put('II', *e)


def read_lnv(data):
    r = Reader(data)
    magic, ver = r.take('4sI')
    if magic != b'LNV\0' or ver != 9:
        raise ValueError('not an LNV v9 file')
    meshes = []
    for _ in range(r.take('B')):
        m = {'path': r.str(), 'name': r.str(), 'head': r.take('HBB')}
        m['head_bytes'] = r.raw(r.take('B'))
        m['points'] = r.many('3f', r.take('I'))
        m['mesh_name'] = r.str()
        nv, npoly, nextra = r.take('III')
        m['verts'] = r.many('3f', nv)
        polys = []
        for _ in range(npoly):
            p = {'id': r.take('I')}
            p['flags'] = r.many('I', r.take('I'))
            p['b'] = r.take('B')
            p['v'] = r.take('3f')
            p['f'] = r.take('f')
            p['extra'] = r.many('I', r.take('B'))
            p['tri'] = r.many('I', r.take('I'))
            p['links'] = r.many('IIIf', r.take('I'))
            polys.append(p)
        m['polys'] = polys
        areas = []
        for _ in range(r.take('H')):
            a = {'id': r.take('H'), 'name': r.str(), 'a': r.take('I'), 'shapes': []}
            for _ in range(r.take('I')):
                t = r.take('B')
                if t == 0:
                    a['shapes'].append((0, r.take('6f')))
                elif t == 1:
                    a['shapes'].append((1, r.take('3f') + r.take('16f')))
                elif t == 2:
                    a['shapes'].append((2, r.take('4f')))
                else:
                    raise ValueError('area shape type %d at 0x%x' % (t, r.o))
            a['first'], a['end'], a['parent'] = r.take('HHH')
            a['children'] = list(r.raw(r.take('B')))
            a['neighbours'] = list(r.raw(r.take('B')))
            areas.append(a)
        m['areas'] = areas
        m['area_tail'] = r.take('HH')
        m['counts'] = r.take('III')
        m['extra'] = [(r.take('I'), r.raw(32)) for _ in range(nextra)]
        m['tree'] = read_tree(r, '8f')
        meshes.append(m)
    if r.o != len(data):
        raise ValueError('%d bytes left over' % (len(data) - r.o))
    return meshes


def write_lnv(meshes):
    w = Writer()
    w.put('4sI', b'LNV\0', 9)
    w.put('B', len(meshes))
    for m in meshes:
        w.str(m['path'])
        w.str(m['name'])
        w.put('HBB', *m['head'])
        w.put('B', len(m['head_bytes']))
        w.raw(m['head_bytes'])
        w.put('I', len(m['points']))
        for p in m['points']:
            w.put('3f', *p)
        w.str(m['mesh_name'])
        w.put('III', len(m['verts']), len(m['polys']), len(m['extra']))
        for v in m['verts']:
            w.put('3f', *v)
        for p in m['polys']:
            w.put('I', p['id'])
            w.put('I', len(p['flags']))
            for f in p['flags']:
                w.put('I', f)
            w.put('B', p['b'])
            w.put('3f', *p['v'])
            w.put('f', p['f'])
            w.put('B', len(p['extra']))
            for e in p['extra']:
                w.put('I', e)
            w.put('I', len(p['tri']))
            for i in p['tri']:
                w.put('I', i)
            w.put('I', len(p['links']))
            for l in p['links']:
                w.put('IIIf', *l)
        w.put('H', len(m['areas']))
        for a in m['areas']:
            w.put('H', a['id'])
            w.str(a['name'])
            w.put('I', a['a'])
            w.put('I', len(a['shapes']))
            for t, v in a['shapes']:
                w.put('B', t)
                w.put('%df' % len(v), *v)
            w.put('HHH', a['first'], a['end'], a['parent'])
            for key in ('children', 'neighbours'):
                w.put('B', len(a[key]))
                w.raw(a[key])
        w.put('HH', *m['area_tail'])
        w.put('III', *m['counts'])
        for v, raw in m['extra']:
            w.put('I', v)
            w.raw(raw)
        write_tree(w, m['tree'], '8f')
    return w.bytes()


def read_way(data):
    r = Reader(data)
    magic, ver, n = r.take('4sII')
    if magic != b'WAY\0' or ver != 16:
        raise ValueError('not a WAY v16 file')
    points = []
    for _ in range(n):
        p = {'id': r.take('I'), 'pos': r.take('3f')}
        na, nb = r.take('II')
        p['a'] = r.many('I', na)
        p['b'] = r.many('I', nb)
        p['c'] = r.many('I', nb)
        p['type'] = r.take('B')
        p['data'] = r.raw({0: 0, 1: 16, 2: 80}[p['type']])
        points.append(p)
    head = r.take('II')
    tree = read_tree(r, '6f')
    if r.o != len(data):
        raise ValueError('%d bytes left over' % (len(data) - r.o))
    return {'points': points, 'head': head, 'tree': tree}


def write_way(way):
    w = Writer()
    w.put('4sII', b'WAY\0', 16, len(way['points']))
    for p in way['points']:
        w.put('I', p['id'])
        w.put('3f', *p['pos'])
        w.put('II', len(p['a']), len(p['b']))
        for key in ('a', 'b', 'c'):
            for v in p[key]:
                w.put('I', v)
        w.put('B', p['type'])
        w.raw(p['data'])
    w.put('II', *way['head'])
    write_tree(w, way['tree'], '6f')
    return w.bytes()


def load(path):
    data = open(path, 'rb').read()
    if data[:4] == b'LNV\0':
        return 'lnv', read_lnv(data), data
    if data[:4] == b'WAY\0':
        return 'way', read_way(data), data
    raise ValueError('unknown file ' + path)


def write_obj(meshes, out, way=None):
    with open(out, 'w') as f:
        f.write('# lp2nav.py: navmesh (o area_N), links (o links), waypoints (o waypoints); LP2 units, Y up\n')
        base = 1
        for m in meshes:
            for v in m['verts']:
                f.write('v %.3f %.3f %.3f\n' % v)
            for a in m['areas']:
                if a['children']:
                    continue
                f.write('o area_%d\n' % a['id'])
                for p in m['polys'][a['first']:a['end']]:
                    f.write('f %s\n' % ' '.join(str(base + i) for i in p['tri']))
            nv = len(m['verts'])
            cen = []
            for p in m['polys']:
                c = [sum(m['verts'][i][k] for i in p['tri']) / len(p['tri']) for k in range(3)]
                cen.append(c)
                f.write('v %.3f %.3f %.3f\n' % tuple(c))
            f.write('o links\n')
            for i, p in enumerate(m['polys']):
                for l in p['links']:
                    if l[0] > i:
                        f.write('l %d %d\n' % (base + nv + i, base + nv + l[0]))
            base += nv + len(cen)
        if way:
            f.write('o waypoints\n')
            for p in way['points']:
                f.write('v %.3f %.3f %.3f\n' % p['pos'])
            f.write('p %s\n' % ' '.join(str(base + i) for i in range(len(way['points']))))


def main(argv):
    if len(argv) < 3 or argv[1] not in ('info', 'obj', 'roundtrip'):
        print(__doc__)
        return 1
    kind, obj, data = load(argv[2])
    if argv[1] == 'roundtrip':
        again = write_lnv(obj) if kind == 'lnv' else write_way(obj)
        print('identical' if again == data else 'DIFFERENT (%d vs %d bytes)' % (len(again), len(data)))
        return 0 if again == data else 1
    if argv[1] == 'info':
        if kind == 'lnv':
            for m in obj:
                leaves = [a for a in m['areas'] if not a['children']]
                links = sum(len(p['links']) for p in m['polys'])
                print('%s: %d verts, %d polys, %d links, %d areas (%d leaves), tree depth %d' % (
                    m['path'], len(m['verts']), len(m['polys']), links, len(m['areas']), len(leaves), m['tree']['depth']))
        else:
            print('%d waypoints, tree depth %d' % (len(obj['points']), obj['tree']['depth']))
        return 0
    way = load(argv[4])[1] if len(argv) > 4 else None
    write_obj(obj, argv[3], way)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
