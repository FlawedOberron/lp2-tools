# Volumes 2026-10-30 (nothing committed, untested in game)
- Rotation (yaw) for every volume effect: editor yaw ring (gizmo allow_yaw), _box in local frame, face_hit/drag
  along turned normals; compiler volume_local (unrotated box + "yaw" in map.json), volume_corners, volume_box =
  rotated bounds; kill = lp2col.kill_top over turned corners; weather limiter turned = scene box shape 2 quad prism
  (8 i32 corners + f32 bottom, height, 0; lp2weather.corners orders them so the ported game test inside_quad holds);
  DLL InBox (packages.h) for gravity / post / water.
- Next per user: compound volumes (Ctrl+Shift+drag a face = new sub-box, volume keeps a list of boxes in its own frame),
  imported mesh volumes (DLL exact, game zones / kill from boxes), then thumbnails, sound post-processing, SpaceWar.
- Compound volumes BUILT (editor-tested only): project volume "boxes": [{"pos": floor centre relative to the volume
  pos in its turned frame, "size"}]. Editor: one mesh / pick shape per box (volumes.sub_boxes / _boxes), face_hit
  per box ("box" index), Ctrl+Shift+drag a face = begin_face(extrude) adds a box out of it; dragging the main box's
  faces keeps the sub-boxes in place; inspector "N boxes" + Remove last box. Compiler volume_parts / all_parts expand
  them for every effect (map.json entries, kill tops, weather zones). Gizmo scale / size spins act on the main box only.
- Ctrl+Shift+right click a volume box deletes it (volumes.delete_box; the main box going promotes the first sub-box; refused on a one-box volume; fly_camera ignores that right press). Input-tested.
