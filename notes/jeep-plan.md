# Jeep (multi-seat light vehicle) plan

User, 2026-11-08: a jeep with physics and multiple seats (driver, gunner, passenger), inspired by Halo's Warthog
(springy, grippy, slides, flies off jumps, runs people over), not a copy: our own model, name and tuning. It needs
run-over behaviour (no stock VS moves fast enough for that to matter). May come with a game mode (GameModes zip
"content.vehicles") or a map.

## Done (2026-11-08 night)
- Driving model: xlive `src/mods/jeep/jeep.h|.cpp`, plain C++, no game types (cm, s, kg, +Y up). Not linked into
  the DLL yet.
  - Rigid body (box inertia, low centre of mass), 4 raycast wheels: spring + damper + bump stop, anti-roll bars,
    tyres on a friction ellipse (sideways grip falls to 0.9x at top speed so it drifts wide rather than tipping),
    4WD drive with a cubic fall-off to top speed (2600 cm/s, about 94 km/h), brakes, reverse, rolling + air drag.
  - Look steering: the wheels turn towards the driver's camera yaw (reversing: mirrored; standing still: the driver
    can look around), lock falls from 32 to 17 degrees with speed; or stick steering (lookSteer false).
  - Handbrake: rear grip drops (power slides), air control (pitch / roll), levelling in the air, flip recovery
    (tipped and slow for 1.5 s, or a player's "flip" press), chassis corners vs world (impulses with friction).
  - RunOver(unit capsule): closing speed at the contact -> Push (< 450 cm/s, or < 900), Knock (900-1500: damage
    0.2-0.9 of a soldier's life, thrown up 350), Kill (>= 1500, thrown far); shares momentum back.
  - Seats: DefaultSeats(): driver front left, gunner at a rear turret (360 deg yaw, -20..55 pitch), passenger
    front right (side cone). Mount / exit points in body space.
- Test: xlive `tests/jeep/jeep_test.cpp` (native g++, command in its header): settle, top speed, braking, look
  turn without rolling, handbrake, ramp jump landing, wall, flip recovery, run-over thresholds. All pass.

## Game side (next)
1. Seat RE (DX11): uVitalSuit +0x2360 mSeatInfo (cSeatInfo: mSeatNum +0x8?, mSeatStatus +0x4?; order in the
   property list is ambiguous), +0x23c0 mRideCheckRange[8] (VSs allow up to 8 seats). cThink mpPilot / mpCopilot /
   mpRide. First in-game step: log every VS type's seat table when one spawns, find a ground VS with >= 2 seats to
   host the jeep (its ride / get-out / seat logic and network sync come with it).
2. Host VS: the jeep is that VS class with our model (as the LP1 VS ports: vs66 on vs06's class). Each frame (VS
   update hook) for a jeep VS: skip the class's own movement, feed the jeep State the driver's pad (+0x1c8 bits,
   stick) and camera yaw, Step(), write position + rotation back (and wheel / turret joints for the model).
3. Ground for the raycasts: either the game's collision ray (cVirtualCursor's: FUN_00fc02a0, result +0x390 pos,
   +0x3d5 static hit; find the plain ray-vs-static call) or our own copy of a custom map's collision mesh from its
   package (a BVH in the DLL: works on every custom map, independent of the game's query). Try the game's first.
4. Seats: driver (throttle / brake = move stick, steer = camera (look steering), handbrake = jump, horn), gunner
   (turret weapon = the host VS's weapon on the turret joint, aimed by the gunner's camera within its arc),
   passenger (keeps their own weapon, aims within the cone). Switch seats with action; flip it with action nearby.
5. Run-over: each frame, units within 6 m (player infos game+0x28[p] -> +0x480 -> +0x40, bots the same) go through
   RunOver; per-unit 0.5 s cool-down. Push = set the unit's velocity; Knock = the game's blown reaction (the Hit
   Stagger work: blown pool, uCharacterBase::vf151) + damage; Kill = lethal damage + a ragdoll throw. Credit the
   driver; friendly fire by the match rules; the jeep's own riders never.
6. Spawning: map editor "Vehicle spawn" marker (kind jeep, respawn time), and mode packages list vehicles in
   mode.json content.vehicles. Respawn when destroyed / abandoned far away.
7. Model: an original jeep in Blender -> lp2model (wheels, suspension arms, steering knuckles, turret yaw / pitch
   joints, seat joints). Damage states later.
8. Online: host-authoritative pose first (the host VS's own sync if it carries position + rotation), test offline
   first. Bots driving: later (route over zones, the gunner seat is easy: aim at targets).

## Tuning knobs (jeep.h Params)
topSpeed, driveForce, grip / highSpeedGrip, rearSlideGrip, maxSteer / highSpeedSteer, springRate / damping /
antiRoll (0 = derived), centreOfMass, airPitch / airRoll / levelling, runOverMin / Knock / Kill.
