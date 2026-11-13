# Bots in VS (next step for bot matches, user 2026-11-13)

Today: the stock brain has RunToYatta -> YattaRideOn -> YATTA (bot-match-plan.md section B). Mounted, a bot only
shoots for 60 frames, waits 150 frames, or gets off past 10 m. No moving, aiming choice, dashing or VS attacks.

Plan:
1. RE (no game changes): how a mounted bot's pad drives the VS. The VS think (cThinkPlayer vf52/53/55 = drop R/L,
   T-ENG; VS special movement pad bits w2 0x800000..0x4000000, split-controls.md), whether MoveTrace / our Resolve
   routing moves a mounted unit, VS health / pilot / seat fields, VS kinds (vs-ids.md) and their weapon slots.
2. Getting in: our routing (Resolve) to a free VS, with a "wants a VS" trait (bold / archetype) and team rules
   (don't steal a teammate's seat, take the nearest free one, VS Show).
3. Piloting in our code (ThinkBody pad): drive toward the target / roam goal over walkable zones only (no grapple /
   jump links for walkers; hover VS can take jumps), keep a VS-sized distance band, strafe/dash when shot at (the
   reaction code we have), fire the VS weapons per range, aim with the cursor-aim path.
4. Getting out: low VS health, out of T-ENG, target unreachable for the VS; and use the jump-off when it's about
   to blow.
5. Brain items (lp2brain.py): replace YATTA's 60/150-frame items with ours; on-foot bots treat enemy VS as targets
   for rockets/grenades and keep out of their way.
Test map: 02 or 04 (VS spawns on both? check).
