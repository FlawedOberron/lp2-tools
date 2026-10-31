# Handoff 2026-10-28: next steps (user's order)

State: NOTHING COMMITTED this session (lp2-tools, lp2-editor, xlive post.cpp/gravity.cpp/packages.*).
Jump packs CONFIRMED in game 2026-10-28 (fine at gravity 1.0 and at low gravity).
The installed xlive.dll is the latest build (cmp-verified). Waiting on an in-game test of the post-volume flicker
fix (constructor viewport flags kept) and the post fade. Ask for the `mods: post:` log lines.
Commit only after the user approves. Export speed work is done (notes/map-editor-plan.md "Export speed").

**2026-10-29: steps 1-2 DONE (untested in game, uncommitted).** lp2bake.py: shadow_splits() traces the sun at 8
points along every sun-facing edge, bisects each lit/shadow change and puts a vertex 12 cm either side of the line
(SHARP_REACH 4 cm ray starts so they stay on their side), plus island midpoints; split_edges() = several points per edge,
side-aware ear clipping (no triangles across the line outside the pair band); the contrast split now ignores the sun.
Passes = 3 + detail/50. Synthetic test (floor + wall): error 0.010 vs old 0.015 at 100%, 0.005 vs 0.015 (old saturates)
at 300%. Battlegrounds preview 100%: +230k verts, 67 s, 3.1 GB (old +162k, 43 s); stage bake 150%: 215k -> 538k,
8.4 -> 19.2 MB, read back clean. Editor: detail slider 0-400, estimate label under it (stage MB vs base, map memory vs
stock, bake RAM vs physical, warnings), memory meter now counts detail. Only the SUN's shadow lines are traced (placed
lights' shadows still go through the contrast split). Backup of the old lp2bake.py: none in repo (it was untracked).

Next, in this order:
1. **Shadow-map vertex splitting**: in lp2bake's detail pass (subdivide / bake_detailed), split triangles along the
   real sun-shadow edges (shadow-map-style visibility test across each triangle) instead of the vertex-contrast guess.
2. **Detail above 100%**: let the lighting detail setting go over 100 (more split vertices), and warn in the editor
   with an estimated memory / vertex cost before baking.
3. **Import LP2 assets**: bring stock LP2 models / pieces into the editor library (Get assets currently rips what
   the library lacks: extend it to LP2's own maps).
4. **Sound volumes**: a "sound" volume effect (audio muffling / reverb etc. while inside), same combo-volume
   pattern as post/gravity/kill (volumes.gd effects + lp2mapc manifest + an xlive mod).
5. **Particle zones & emitters**: placed effect emitters and zones that spawn particles (base map's placed effects
   are removed at the moment: lp2mapc "7 placed effects" leftovers).
6. **Sound nodes**: placed point sound sources.
7. **Random logic for both** (particles + sounds): random timing, offsets, volume, pitch etc., each as a min-max range.

Still open from before: map fog (distance/ground) doesn't render in game, then fog zones (rSceneBox2 zone fog);
thumbnail game side (id221 GFx frames for maps 13/14); screen-space filters; damage-over-time / heat-regen volumes;
Windows test of the multi-core export in the bundled Python before the next release.

New idea (user 2026-10-29): **Override volume** effect. In the inspector pick a list of other volumes (by id); while
the player is inside the override volume, those volumes' effects don't apply (e.g. a safe room inside a
damage-over-time zone, a normal-gravity pocket inside a low-gravity area). Editor: volume ids + a picker in
volumes.gd; lp2mapc writes `overrides: [ids]` in the manifest; DLL: each tick, collect the volumes the player is in,
drop any listed by an override volume they're also in, then apply the rest. Not slotted into the order yet.

2026-10-29 later: **jagged shadows / sparkly lines fixed (v2, untested in game)**. Cracks were T-junctions: an edge's
copies (next block, seams: 115k on Battlegrounds) were split separately; now _EdgeSet splits by position (open edges
at 200%: v1 +115k, v2 +16k with the same open length 109 km = no new cracks). Sun tests every 10 cm (4-48 per edge),
the pair spaced 12 cm from the LINE (direction from a probe crossing 10 cm beside it). Battlegrounds 200%: 158 s, 4.2 GB.
User ideas: **godrays** (engine has uGodrayFilter / uLightShaft / uSynchroLightShaft / uLightScattering*) as a volume
effect + placed shafts, and they want lighting / fog / weather / godrays **per layout** (layout-dependent environment).
**Decals**: no decal class found by name (uProjectionShadow is a projected-texture shadow); plan = baked mesh decals in
the editor (clip stage triangles under a projected quad, offset, alpha material). Engine shadows: uLightSpaceShadow /
uInGameLightSpaceShadow (realtime sun shadow map), uShadowRegion (+ capsule/cuboid/spot/point) not decoded yet.
- 2026-10-29: VS / weapon / post markers were black: LP2's colour maps are dark (mean ~26/255; the game's shader lifts
  them). lp2library.py GLB_VERSION 2: per-model brightness lift (brightened(): mean -> 110, p95 <= 240, gain <= 4),
  flat faces dropped, faces on both sides of a plate get split normals; library rebuilt from raw (34 s, 207 assets).
- 2026-10-29 in-game test (user): kill volumes WORK. Still dark + navy, darkness flickers, no fog visible.
  Findings: (1) post.cpp added a 2nd uPlanetColorCorrectFilter; the map's Filter scheduler already has one (same
  class) -> they alternated = flicker. REWRITTEN (installed, cmp OK, untested): class vtable vf6 patched in place,
  the map's own filter gets the volume grade in correctors 13-15 (off outside volumes); logs "grading the map's
  colour filter", "camera in post volume N" / "out of post volumes"; PostTick removed. (2) Battlegrounds uses
  Frozen Wasteland's (15) tone curves (R .26->.11) on a dim env (ambient .15 vs 15's .5-.6) -> navy/dark.
  Editor grade dropdown now shows the applied grade. (3) Stock LP2 stage vertex light is dark too (median 00 .09,
  03 .01, 06 .02) -> the stage must get realtime light as well: the "pixel = tex x (2c)^2.2" model is suspect.
  (4) Fog: installed package's rSceneBox2 zone fog is ON and matches stock's layout (Filter scheduler only
  references the SceneBox); maybe hidden by the grade. Next test: Neutral grade, re-install, report flicker / fog.
- 2026-10-29 test 2 (user): flicker GONE, brightness normal (Neutral grade), post zone works but goes dark on
  first entering / leaving; no fog (distance or height). Log: "grading the map's colour filter" once, never
  "camera in post volume": uColorCorrectFilter::vf6 (DX9 0x478720 / DX11 0x478fe0) sits in 3 vtables (DX9 rva
  f56ca8 planet, f56ce8 sibling, 12cfc20 base; DX11 f66ca4, f66ce4, 12dfcbc): only the first was patched. Now all
  3; the filter updated most per 1 s window is graded, others get correctors 13-15 off; logs the filters seen.
  Installed, cmp OK, untested. Fog: installed rSceneBox2 zone fog is right; stage materials' flags (+0/+4) match
  stock (+0x24 = env cube map texture slot, not fog). Next fog tests: DX11 run; extreme fog (start 0, end 3000,
  red, density 1) to see if anything draws.
- 2026-10-29 test 3 (DX11): no fog in DX11 either. Post: map filter now updates ours (camera in/out logged,
  fade 0.5 s) but still "goes dark" at the edges. vf6 RE: type 8 = diag(x, y, z, 1), 5 = saturation (x), 9 falls
  through into 10 = levels (factor..factor2): matrices fine. Theory: at an exactly neutral grade the game skips the
  filter pass, and the pass switching on/off at the edge = dark moment (Neutral grade makes it identity outside).
  Fix installed (cmp OK, untested): our tint never exactly 1 (kNearOne 0.999), correctors always on.
  Fog next: extreme fog test (start 0, end 3000, red, density 1) from the editor; see if stock map 00 shows fog.
- 2026-10-29 FOG FOUND: it renders. Test at strength 1: height fog blue below the line (correct); distance fog
  (red) drew BLACK incl. the sky. mDistanceType 4 (copied from stock 00) ignores mFogColor; stock 07 / 15 use 0
  with their colour. lp2scenebox.from_project now writes type 0 (untested in game; re-export needed). Earlier
  "no fog" = 0.65 black distance fog + 0.13 grey height fog on a dark scene.
- 2026-10-29 editor: height fog previews in its own colour (heightfog.gdshader: full-screen quad on the camera,
  world height from the depth buffer, none at top -> colour x strength at bottom); Godot's depth fog = distance
  fog only. Render-tested in a scratch scene (Forward+); not yet seen in the editor by the user.

## 2026-10-30: step 3 (Import LP2 assets) built, untested in editor/game
- lp2stockmaps.py: every stock online map (00-12, 15) -> library map LIB/lp2/mapNN (stage models from _scr.arc in map
  space, not sky/shadow/kage; collision atari*/tama* from arcXmlTmpPC/variable/_v.arc with surfaces kept).
  lp2library get builds missing ones (once; --force rebuilds); Browser shows "LP2 map <name>" groups, no editor change.
- lp2col.write_sbc1: per-triangle surface flags (0 = the default) so LP2 materials survive (0x4000xxxx <-> 0x8000xxxx).
- ~85 MB per map (~1.2 GB), ~30 s per map. Stock lightmaps not kept (constant top light; the bake relights).
- Known gaps: surfaces the target's table lacks fall back to its first; scheduler-placed objects / effects / skies
  not included (only stage models).

## 2026-10-30: weather SOLVED, limiter volumes, water research
- Cause: mWeatherRate 100. DX11 uPlanetEffectVFRWeather::vf80 (0xde0bc0): R = rate<=50 ? rate*(zone%/100)
  : rate + (100-rate)*(100-zone%)/100; particles = 10*R, 0 if <11 or >989. Rate 100 -> 1000 -> nothing.
  lp2mapc.weather_rates now maps amount 0..100 -> rate 0..50 (stock range; limiters only work <=50). User: works.
  Dead ends: skybox / collision lid, field set fs1-6 (local interior effects), slot 13, texture residency.
  Bisect method that found it: stock package + our arcs swapped in one at a time (file -> class -> track).
- Weather limiter volumes: volume key "weather": % (0 = none; old "no_weather" migrates); lp2weather.zones writes
  zone weather [1, %, kind] at priority 7. Editor inspector "Weather %"; fog window button. Untested in game.
- User wants custom weather effects later (stock snow looks poor).
- Water (research only): sGameManager (main) +0x261 water exists, +0x2ac height. Height-at-position lookup
  DX11 0x7e1790 thiscall(main, pos, &h): FUN_0086a0f0 (rWaterBoundary? used first on areas 4-7, 4-8, 7-5) else
  scene-box zone lookup kind 0x40 (FUN_0086df90 -> FUN_0086dac0(0x40), height at contents +0x14). Underwater test
  FUN_007fcde0(pos) = pos.y < height, 290 callers (weapons, chars, effects). So per-area water may be data-only
  (zones / water boundary) or one DLL hook on 0x7e1790 (+ DX9 twin). Character "lighter" = stage flag 0x04000000
  + that test (FUN_009bc860).
- Limiter fix: cell zone lists are first-match (FUN_0086dac0 returns the first entry holding the point, -1 ends);
  limiters now go to the front of each cell's 16 entries, smallest first.
- Water volumes step 1 BUILT (untested): water.cpp redirects the 7 + 2 water lookup calls (DX11 0x7e1790 / 0x7e1810,
  DX9 0x7d28d0 / 0x7d2950); map.json "water_volumes" [{min,max}]; any water volume sets the stage's underwater
  (lighter) flag. Editor volume effect "water": true. Not done: visible surface, camera underwater look (+0x2ac readers).
- User's next list: thumbnails, sound post-processing in volumes/zones, then the "SpaceWar" piggy-back (user has an
  LP2 ISO now). User asked for rotated (yaw) volumes: plan = yaw on every effect (DLL boxes in local frame, kill quad
  rotated, weather zone as shape 0x2 quad prism if its format is as it looks).
