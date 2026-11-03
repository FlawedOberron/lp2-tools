// Recast navmesh for lp2navgen.py: triangle soup in, triangle polygons out (max 3 verts per polygon, so each
// polygon is one LNV triangle). Units are LP2's (cm, Y up).
//   navgen IN.bin OUT.bin cs ch height radius climb slope [detail]
// detail: the detail mesh's triangles instead (they follow slopes and folds), neighbours all -1
// IN:  u32 nv, u32 nt, nv x 3f, nt x 3i
// OUT: u32 nv, u32 np, nv x 3f (cm), np x 3i (vertex ids), np x 3i (neighbour polygon per edge, -1 none)
#include "Recast.h"

#include <cmath>
#include <cstdio>
#include <cstring>
#include <map>
#include <tuple>
#include <vector>

int main(int argc, char** argv)
{
	if (argc < 9) {
		fprintf(stderr, "usage: navgen IN OUT cs ch height radius climb slope [detail]\n");
		return 2;
	}
	FILE* f = fopen(argv[1], "rb");
	if (!f) {
		return 1;
	}
	unsigned nv = 0, nt = 0;
	fread(&nv, 4, 1, f);
	fread(&nt, 4, 1, f);
	std::vector<float> verts(nv * 3);
	std::vector<int> tris(nt * 3);
	fread(verts.data(), 4, verts.size(), f);
	fread(tris.data(), 4, tris.size(), f);
	fclose(f);
	float cs = atof(argv[3]), ch = atof(argv[4]);
	rcConfig c;
	memset(&c, 0, sizeof c);
	c.cs = cs;
	c.ch = ch;
	c.walkableSlopeAngle = atof(argv[8]);
	c.walkableHeight = (int)ceilf(atof(argv[5]) / ch);
	c.walkableClimb = (int)floorf(atof(argv[7]) / ch);
	c.walkableRadius = (int)ceilf(atof(argv[6]) / cs);
	c.maxEdgeLen = (int)(1200 / cs);
	c.maxSimplificationError = 1.3f;
	c.minRegionArea = (int)rcSqr(8);
	c.mergeRegionArea = (int)rcSqr(20);
	c.maxVertsPerPoly = 3;
	c.detailSampleDist = 6 * cs; // 0 crashes rcBuildPolyMeshDetail
	c.detailSampleMaxError = ch;
	rcCalcBounds(verts.data(), nv, c.bmin, c.bmax);
	rcCalcGridSize(c.bmin, c.bmax, c.cs, &c.width, &c.height);
	rcContext ctx(false);
	rcHeightfield* hf = rcAllocHeightfield();
	if (!rcCreateHeightfield(&ctx, *hf, c.width, c.height, c.bmin, c.bmax, c.cs, c.ch)) {
		fprintf(stderr, "heightfield %d x %d failed\n", c.width, c.height);
		return 1;
	}
	std::vector<unsigned char> areas(nt, 0);
	rcMarkWalkableTriangles(&ctx, c.walkableSlopeAngle, verts.data(), nv, tris.data(), nt, areas.data());
	rcRasterizeTriangles(&ctx, verts.data(), nv, tris.data(), areas.data(), nt, *hf, c.walkableClimb);
	rcFilterLowHangingWalkableObstacles(&ctx, c.walkableClimb, *hf);
	rcFilterLedgeSpans(&ctx, c.walkableHeight, c.walkableClimb, *hf);
	rcFilterWalkableLowHeightSpans(&ctx, c.walkableHeight, *hf);
	rcCompactHeightfield* chf = rcAllocCompactHeightfield();
	rcBuildCompactHeightfield(&ctx, c.walkableHeight, c.walkableClimb, *hf, *chf);
	rcErodeWalkableArea(&ctx, c.walkableRadius, *chf);
	rcBuildDistanceField(&ctx, *chf);
	rcBuildRegions(&ctx, *chf, 0, c.minRegionArea, c.mergeRegionArea);
	rcContourSet* cset = rcAllocContourSet();
	rcBuildContours(&ctx, *chf, c.maxSimplificationError, c.maxEdgeLen, *cset);
	rcPolyMesh* pm = rcAllocPolyMesh();
	if (!rcBuildPolyMesh(&ctx, *cset, c.maxVertsPerPoly, *pm)) {
		fprintf(stderr, "poly mesh failed\n");
		return 1;
	}
	rcPolyMeshDetail* dm = rcAllocPolyMeshDetail();
	rcBuildPolyMeshDetail(&ctx, *pm, *chf, c.detailSampleDist, c.detailSampleMaxError, *dm);
	// vertex heights from the detail mesh (its first verts per polygon are the polygon's, at surface height)
	std::vector<float> out(pm->nverts * 3);
	std::vector<int> seen(pm->nverts, 0);
	for (int i = 0; i < pm->nverts; i++) {
		const unsigned short* v = &pm->verts[i * 3];
		out[i * 3] = pm->bmin[0] + v[0] * pm->cs;
		out[i * 3 + 1] = pm->bmin[1] + v[1] * pm->ch;
		out[i * 3 + 2] = pm->bmin[2] + v[2] * pm->cs;
	}
	for (int p = 0; p < pm->npolys; p++) {
		const unsigned short* poly = &pm->polys[p * pm->nvp * 2];
		const unsigned* meshInfo = &dm->meshes[p * 4];
		for (int k = 0; k < pm->nvp && poly[k] != RC_MESH_NULL_IDX; k++) {
			if ((int)meshInfo[1] > k && !seen[poly[k]]) {
				out[poly[k] * 3 + 1] = dm->verts[(meshInfo[0] + k) * 3 + 1];
				seen[poly[k]] = 1;
			}
		}
	}
	if (argc > 9 && !strcmp(argv[9], "detail")) {
		// the detail mesh's triangles (they follow the surface: sample points where the polygon strays more than
		// detailSampleMaxError from it), vertices welded by position so neighbouring triangles share edges;
		// neighbours all -1 (the caller links by shared edges)
		std::map<std::tuple<int, int, int>, int> weld;
		std::vector<float> dv;
		std::vector<int> dt;
		for (int p = 0; p < pm->npolys; p++) {
			const unsigned* m = &dm->meshes[p * 4];
			int idx[256];
			for (unsigned k = 0; k < m[1] && k < 256; k++) {
				const float* q = &dm->verts[(m[0] + k) * 3];
				auto key = std::make_tuple((int)lroundf(q[0] * 10), (int)lroundf(q[1] * 2), (int)lroundf(q[2] * 10));
				auto it = weld.find(key);
				if (it == weld.end()) {
					it = weld.emplace(key, (int)(dv.size() / 3)).first;
					dv.insert(dv.end(), q, q + 3);
				}
				idx[k] = it->second;
			}
			for (unsigned t = 0; t < m[3]; t++) {
				const unsigned char* tr = &dm->tris[(m[2] + t) * 4];
				int a = idx[tr[0]], b = idx[tr[1]], c = idx[tr[2]];
				if (a == b || b == c || a == c)
					continue;
				dt.push_back(a), dt.push_back(b), dt.push_back(c);
			}
		}
		f = fopen(argv[2], "wb");
		unsigned onv = dv.size() / 3, onp = dt.size() / 3;
		fwrite(&onv, 4, 1, f);
		fwrite(&onp, 4, 1, f);
		fwrite(dv.data(), 4, dv.size(), f);
		fwrite(dt.data(), 4, dt.size(), f);
		std::vector<int> none(dt.size(), -1);
		fwrite(none.data(), 4, none.size(), f);
		fclose(f);
		fprintf(stderr, "grid %d x %d, %d polys -> %u detail verts, %u triangles\n", c.width, c.height, pm->npolys, onv, onp);
		return 0;
	}
	f = fopen(argv[2], "wb");
	unsigned onv = pm->nverts, onp = pm->npolys;
	fwrite(&onv, 4, 1, f);
	fwrite(&onp, 4, 1, f);
	fwrite(out.data(), 4, out.size(), f);
	for (int p = 0; p < pm->npolys; p++) {
		const unsigned short* poly = &pm->polys[p * pm->nvp * 2];
		for (int k = 0; k < 3; k++) {
			int v = poly[k] == RC_MESH_NULL_IDX ? -1 : poly[k];
			fwrite(&v, 4, 1, f);
		}
	}
	for (int p = 0; p < pm->npolys; p++) {
		const unsigned short* poly = &pm->polys[p * pm->nvp * 2];
		for (int k = 0; k < 3; k++) {
			unsigned short n = poly[pm->nvp + k];
			int v = (n & 0x8000) ? -1 : n;
			fwrite(&v, 4, 1, f);
		}
	}
	fclose(f);
	fprintf(stderr, "grid %d x %d, %d verts, %d polys\n", c.width, c.height, pm->nverts, pm->npolys);
	return 0;
}
