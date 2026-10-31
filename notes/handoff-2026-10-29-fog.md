# Fog investigation 2026-10-29 (continues handoff-2026-10-28-next.md)
- Type 0 + red strength 1 installed (verified in the package, all 45 zones): distance fog still BLACK.
- Decompile: distance fog = uColorFog (0x210; DX9 vf3 006d93a0 props, vf9 006d99f0 draw). Props: mDistanceType
  (+0xd0), mFogColorType (+0xd4), mpFogTable (+0x104, a texture), mColor (+0xf0), mR/G/BCurve. vf9: colour type 1
  OR distance type 4 -> a pass drawn from mpFogTable; another path below not traced yet. We never set
  mFogColorType (not in rSceneBox2's fog record as parsed).
- Test installed: Battlegrounds built with stock 15's exact zone-0 fog record (type 0, colour .555 .705 1 a .919,
  2000..12000, height off) -> game Maps/Battlegrounds.zip. User's own build saved as
  scratchpad Battlegrounds.user-1521.zip (re-export from the editor restores it anyway).
  Light blue fog = our values are wrong; black = something else in our map (uColorFog setup / fog table).

## 2026-10-29 later: fog RE findings
- In-game shot with stock 15's record: the whole frame black, incl. the player at ~3 m. So the fog ignores start/end (depth reads as far?) and its colour is ~0, not a falloff problem.
- uColorFog = campaign events only (event_lp2\e6xx/d0xx + ONLINE_06 filter_windows' ColorFogFilter). Not the MP zone fog.
- sSceneBox2 (global DAT_01852d38) creates uLightScatteringFog at +0x854 (= the scheduler's mpAreaLScattering) and +0x858 (Sub) in FUN_00869ae0. Fields: +0x24 mRenderType, +0x80 mHeightType, +0x88/8c HeightStart/End, +0x90 HeightDensity, +0xa0 HeightColor, +0xd0 Rayleigh, +0xe0 (wavelengths), +0xf0 SunColor, +0x100 SunDir, +0x110 MieDirective, +0x114 Density. It has no distance-fog colour field.
- cMaterial has a FogEnable flag (vf3 00543e80, accessor LAB_005423d0/f0; on-disk exe encrypted, so the bit is unknown). The zone distance fog is probably material-shader fog.
- Our scattering and sun values match stock (mSunDir y < 0). Our filter schedulers have no fog tracks (stock 06's filter_windows does: mFogData/mFogColor/Start/End).
- Test: removed Maps/Battlegrounds.zip, so stock Battlegrounds loads (layout 0 = type 4 strength 1). If stock is also black or hazeless, it's the engine under Proton (or our DLL), not our package.
- Fog volumes: scene box layouts ARE shaped volumes (priority, shape box/cyl/sphere, mFogBlendFrame blending), so fog volumes come free once fog renders.
- Desecration (stock 00) shows normal green haze in game, so the engine is fine and our package is the cause. Type 4 fog takes its colour from the scattering (00's green).
- Test with stock schedulers + our scene box: the sky gets green haze, but all geometry (incl. the player) is black. So schedulers are ruled out.
- Lead: every stock map's layout 0 has env "on" = 1 (00/10 with rnl_cross_CM2; 15 with no texture). lp2scenebox.neutral() writes 0. Test package BattlegroundsEnvOn.zip = Fog15 + layout 0 env on=1 (no texture). If that fixes it, neutral() should keep layout 0's env flag.
- Swapping in stock 00's scene box itself hangs loading (it references stock field sets/effects).
- Env-on test: still black and blurry. Ruled out: env flag, schedulers, fog record. Restored the user's build afterwards.
- Package vs stock: same sa/ shader packages. Differences: _scr.arc (stage models/textures), scene box (layouts/grid/bounds), objsets, water (on00_water emptied by lp2clean: it also holds o00_enkeimoya = distant haze and online00_zblur / zblur_plane = depth blur), Occluder.
- Theory to test next: the sun's real-time shadow covers everything (sky dome or other stage mesh casting shadows?). The scattering in-scatter and type-0 fog colour may be sun-shadowed, which would leave the sky fine and all geometry black. Check rModel stage mesh shadow-cast flags, and whether characters receive sun light in our maps.
- uWater (vf3 006bd0a0) has mAutoFog, mWater/AirFogColor/Start/End, mShadowFogColor.
- Shadow lead: stock scr arc has online00_shadow (1 mesh, flags 0xffff, stride 20, fmt 0xa7d7d02f, 1422 verts, bbox x -10631..3759, z -10575..12745: a partial caster, not the whole map). Ours = lp2stage --empty stub (1 mm triangle at y -100000, stage format). Same for online00_car1-4 stubs. The user build has no sky dome (car1 is the stub).
- Test BattlegroundsShadow.zip = Fog15 + stock online00_shadow (texture slot renamed to our online00_CM-01). If fog works, the stub's far-below bounds break the shadow fit; fix lp2stage's stubs (place them inside the map, or emit a real shadow model).
- Shadow test (stock online00_shadow): still black. Not the cause. User: still worth generating a real shadow caster from the map geometry (TODO: lp2stage emits online00_shadow from the stage, stride-20 fmt 0xa7d7d02f, mesh flags 0xffff; reverse that vertex format first).
- Reverse bisect: BattlegroundsStockPlusGeo.zip = stock 00 arcXmlTmpPC main + _v (stock scene box, field set, schedulers, effects, water) + our geometry group (ScrList, atari/tama collision, havok, AreaHit, Occluder, InitPos) + our _scr.arc.
- StockPlusGeo result: terrain black, sky haze green, so the cause is in the geometry group. Materials only differ in ways stock also uses (+0x24 CM index 1 vs stock 4 = each list's CM). Scr schedulers match stock.
- Our ScrList drops on00_water (holds o00_enkeimoya = distant mist, online00_zblur / zblur_plane = depth blur, water models), online00_fallout and area4_UnderWater0.
- Test maps installed as separate packages (on StockPlusGeo): FogA = stock ScrList (paths renamed online00 -> lp1bg900, same length), FogB = stock Occluder, FogC = stock AreaHit (main + _v), FogD = all three. Battlegrounds.zip = the user's own build again.
- Note: zipfile writestr(zin.getinfo(n)) mutates the ZipInfo; reusing the source zip afterwards fails. Write by name.
- Fog A-D: all pitch black (A/D show the stock ash; C/D green sky). Ruled out: ScrList/on00_water, Occluder, AreaHit. Removed A-D from Maps.
- Our stage header: sphere r 1030657 cm, bbox +-718363 x/z, y -29247..318104 (stock: r 322520, +-322224, y -123248..150911). Stubs (shadow, car1-4) at y -100000.
- Installed FogE (stage header bounds -> stock), FogF (stub -100000 floats -> 0), FogG (both), on StockPlusGeo.
- FogE/F/G: all black. Bounds and stubs ruled out. Stage vertex alpha = 255 in stock too (fmt 0x49B4F022).
- Installed FogH (all stock + our _scr.arc only) and FogI (all stock + our main/_v collision group from StockPlusGeo, stock _scr.arc). Removed E-G.
- FogH and FogI: BOTH black. FogI = stock Desecration geometry + stock env, only our collision group. So ANY package in slot 13 is black and the same files in slot 0 are fine: per-slot / per-map-number engine behaviour, not our data.
- Ruled out: Renumber (only "area_online_"/"rader_map_7_" strings); missing MaterialSkipList for 13 (map 15 has none and works).
- Unpacked exe for disassembly: ~/Projects/lp2-tools/unpack/LP2DX11.exe.unpacked.exe (objdump works; the on-disk exe is encrypted). FogEnable = cMaterial +0x10 bit 0x40.
- Fog manager = sSceneBox2 + 0x990 (FUN_0086d5f0: FUN_00f69070(sb+0x990, sb+0x854); jmp FUN_00f6a400(sb+0x990)). sSceneBox2 global DX11 RVA 0x1452d38.
- TEMP probe in gravity.cpp (FogProbe in CharGravity, DX11 only): logs "fogprobe:" every 5 s, manager +0x990 (0x6a0 B) and scatter unit. REMOVE after the diff. Installed. Plan: user plays Desecration, then FogI, then diff the dumps.
- Probe diff, Desecration (7/0) vs FogI (7/13): manager +0x990 (0x6a0 B) and scatter unit IDENTICAL except two pointers (+0x10/+0x14). sSceneBox2 flags identical (0005a1fd). So the fog state is right; the difference is downstream (render).
- The unpacked s13 shader package is byte-identical to stock 00 (only the entry name renumbered). Stock ships a 21 KB Area_ONLINE_13 shader package (DX9+DX11).
- FUN_00878ff0 (area init): per-map FUN_0084db50 modes (online 2,3,5,6,8,11 -> 5; 7 -> 6), stage +0x14598 flag clears.
- FogJ = FogI with no DLL map features (no jump packs, gravity/post volumes), to rule out our DLL.
- ROOT CAUSE: FogJ (no DLL map features) fine; K (jump packs) and M (gravity volume) fine; L (post volume only) black. post.cpp used corrector type 9 for levels. Type 9 is NOT levels (FUN_00472340: a colour-space transform scaled by mFactor.x, which is 0 for us); type 10 is levels ((x - f)/(f2 - f), alpha identity). That broke the scene alpha that fog / DOF read, so any fog drew black and the frame blurred, on every map with a post volume (in or out of it).
- Fix: post.cpp levels -> type 10 (both builds, shared code). Probe removed from gravity.cpp. Installed, cmp OK. Test map FogL left in Maps; Fog J/K/M removed. User's Battlegrounds has a post volume, so its own fog should now work after this DLL.
- Still pending: the post-zone smooth fade test; real shadow caster from geometry (see above); fog volumes (= more scene box layouts).
- After the type-10 fix: the user confirms Battlegrounds looks correct and the post zone works. But distance fog is invisible: the user's record is type 0, red (1,0,0) strength 1, 6000-12000 cm, height fog 700..50 blue.
- Test maps FogType1..4 = the user's Battlegrounds with mDistanceType 1..4 on every fog-controlled layout (type 0 = Battlegrounds itself). Removed FogL. Copy of the current user build: scratchpad/Battlegrounds.current.zip.
- FogType1-4: no distance fog on any. Reason: the zone's mDistanceType is never copied. Fog manager FUN_00f684e0 creates the MP distance-fog unit = uColorFog at mgr+0x10 with mDistanceType 4, mFogColorType 1 (fixed), plus uLightScatteringFog at mgr+0x14. FUN_00f68ba0 copies the zone's colour -> +0xf0, alpha -> +0xe4 (strength), start/end -> +0xd8/+0xdc, curves -> +0x10c (distance), +0x14c/18c/1cc (R/G/B). vf9 builds mpFogTable (+0x104, a render target) from the curves (RGB when colour type 1, distance when type 4). vf7: type 4 range = 1/(end-start); techniques 0x72e313c3 / 0xf5a4a3cb. So mDistanceType in our export doesn't matter.
- Stock 00 main zone: start -1000, end 30000, colour .506/.641/.703 a1 (shows green = scattering). 10: 1000-20000, .885/.986/.997.
- Test maps FogT1 (Desecration values), T2 (stock 00 filter schedulers = its atmosphere), T3 (white), T4 (T1+T2), on Battlegrounds.current.
- FogT1 (Desecration values) and T3 (white): no fog. T2/T4 (Desecration atmosphere): yellow-green fog. So MP distance fog colour = atmospheric scattering (mpAreaLScattering: sun colour x Rayleigh/Mie), not mFogColor. Our online01 clear sky (Mie 3) is too thin to show.
- Test maps T5 (Mie 100), T6 (Mie 100 + red sun 10/1.5/1.5), T7 (Mie 30), T8 (Mie 100 + density .7 + MieDir -.6), on Battlegrounds.current, written into every filter scheduler's mpAreaLScattering keys. Goal: map the editor's fog colour / density onto sun colour / Mie.
- T5-T8 (Mie 100 / red sun / Mie 30 / Mie+density+dir): no fog on geometry. Only the sky tint changes (T6 red sky). T2 (all stock 00 filter schedulers) DID fog the geometry yellow-green.
- Test maps T9 (our filters + all stock 00 mpAreaLScattering tracks), T10 (stock filters + our scattering), T11 (T9 but our sun colour/dir), T12 (T9 but our Rayleigh). Decides scattering vs other filter objects (ToneMap/DOF/Bloom/CC).
- Results: T9 (stock scattering) yellow-green fog on geometry; T10 (stock filters, our scattering) none; T11 (our sun) faint grey-blue; T12 (our Rayleigh 17/14.8/13.9) sky haze, buildings barely. => MP distance fog = aerial perspective from mpAreaLScattering. Rayleigh values are wavelength-like (uLightScatteringFog vf7: 1/x^4), lower = more scattering; per-channel ratio = colour. Stock 00: 10.4/10.5/13, Mie 100, dir -0.6, density .7, sun (10,9,4). lp2light's SCATTER (online01 clear sky) is why our maps had no fog.
- Calibration maps T13 red (9.5,16,16), T14 blue (16,16,9.5), T15 grey thick (10.5 x3), T16 grey thin (13 x3), all on T9 (stock scattering, only Rayleigh changed).
- Calibration T13-16: red = very thin red fog, others barely visible. Scattering fog is too subtle and fiddly to drive from the editor.
- NEW APPROACH (installed, untested): gravity.cpp ColourFog(), called every frame from CharGravity on package maps (g_active): unit = *(sSceneBox2 + 0x990 + 0x10); sets +0xd0 mDistanceType = 0 and +0xd4 mFogColorType = 0, so the zone's mFogColor / alpha / start / end draw directly. sSceneBox2 global: DX11 RVA 0x1452d38, DX9 0x1442c98 (DX9 manager also at +0x990: lea 0x990(%esi) at 85dfba; unit creation FUN_00f58680). Test maps T13-16 removed; Maps has the user's Battlegrounds (red fog 60-120 m).
- If types 0/0 draw nothing or black: try distance type 1 or colour type 0 with distance type 4 (vf7 technique table above).

## SOLVED 2026-10-30: distance fog on package maps
- Cause: online maps' scheduler turns on the fog managers' atmosphere mode (manager flags +0x694 bit 0x200 =
  sSceneBox2 +0x1024 / +0x16c4, mirrored from +0x16d0 0x2000 by FUN_0086a540, called from the event/scheduler
  interpreter FUN_0087e290 case 0x1a). In that mode the zone fog reaches the uColorFog only when manager 0x40, and the
  haze comes from mpAreaLScattering (scatter unit gets 0x800, colour unit loses it).
- Fix (gravity.cpp ColourFog): every frame on package maps clear 0x200 on both managers. Nothing else: the campaign
  state (unit flags 14c1a incl. 0x4000, types 4/1, fog table from the curves) is what draws. User confirmed FogStock +
  Battlegrounds correct in DX11. DX9 offsets identical (decomp 0085.c:7769) - untested in game.
- Dead ends: forcing types 0/0 (not copied / wrong technique), clearing 0x4000 (not a hide flag), clearing 0x800.
- Our geometry/materials are fine (stock Desecration ignored the fog identically under atmosphere mode).
- 2026-10-30 user: fog correct in game, maybe a bit subtler than the editor preview (check preview vs game curve
  later). Jagged shadows still an issue: come back to it.
