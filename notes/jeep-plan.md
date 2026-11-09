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

## What the 2026-11-09 attempts showed (keep)
Approach tried: every VS on a map package (lp2jeepmap.py: Frozen Wasteland (Jeeps), all layouts' VS -> type 0x16)
dressed as a rigid jeep model on vs16's skeleton (lp2jeepmodel.py, uVs16.arc override in Mods\jeep) and its pose
overwritten each update by the jeep core (jeep_drive.cpp, from oneway.cpp's unit update wrapper). Result: they walk
like VS. Findings:
- RulesLocalSlot() stays -1 mid-match: g_localIndex is only set in ControlUpdate, which runs while a player is
  dead. Nothing that needs "the local player" works until that's fixed (fallback: the entry with a camera).
- VS / character updates run on several worker threads at once (log thread ids): shared state needs a lock.
- Never measured: whether the game moves a VS again after our write (the probe needed the local slot).
- vs16 is the vs06 family (bike <-> robot): its own state machine and motions keep running under any pose write.
- Riding: Body(slot) is the soldier while riding. Leads: cThink mpPilot +0xb4, mpCopilot, mpRide +0xbc (DX11
  0x905eb0 registration), uControl mRidedVsGITK / mRideOffReason, uCharacterBase +0x1790 mpRideReservedVs.
Kept, working: the driving core + native tests, the map package (loads, 17 VS spawn), the model writer's rigid
format, ForceThrow / CharacterPlace, the jeep ground (.col) per map package.

## Plan (user, 2026-11-09): one step at a time, each proven in game before the next
1. **The jeep asset**: 3 seats (driver, gunner, passenger) and a proper skeleton: root, chassis, per wheel a
   suspension arm + wheel (front: steering knuckle), turret yaw + pitch, seat joints, exit points. Model rigid per
   joint (lp2model FMT_RIGID). Open: which VS class hosts it (needs >= 3 riders: mRideCheckRange[8], cSeatInfo;
   survey stock VS seat tables; vscb transport 0x28/0xa8 carries riders), joint ids its code expects.
   In-game check: it spawns, renders, can be entered.
2. **Physics drives the skeleton**: the core owns the root pose and the joints (suspension compression, wheel spin,
   steering). The host VS's own movement / motion update skipped for jeeps (RE: the uVitalSuit move + motion
   update; skip it, keep ride logic). Riders sit and do nothing yet; it lands and slides along the floor.
   In-game check: drop one, it settles on its wheels; push it (grenade), it slides. Prereq: a "can we move a
   VS at all" test (nudge a ridden stock VS 1 m once: stays or snaps back).
3. **Generic wheeled-vehicle controller**: jeep.h Params -> a vehicle config (N wheels with position, radius,
   suspension, driven / steered / braked flags, engine force curve, top speed, steering lock vs speed, grip, mass,
   centre of mass), loadable from the mode / map package (content.vehicles). Steering left / right and engine
   force to the wheels as inputs. Native only (tests/jeep): can be done without the game.
4. **Driver controls**: while someone is in the driver seat, their pad goes to the controller (steer, throttle,
   brake, handbrake). Needs: the local slot fix, the ride pointer (who sits where), the pad's analog stick
   fields (only the button bits +0x3b8 / +0x3c0 are known). Remote drivers: input or pose sync over the network.
5. **Turret seat**: like stock turrets (vs03 / om0014 column, 150-152 built-in joints) but parented to the jeep's
   turret joints instead of a fixed spot; weapon picked from any VS weapon id (vs-mounts.md: mounts 100-103,
   weapon ids 0x41..0x6d; weapon-workbench.md).
6. **Passenger seat**: sits, keeps aiming and firing their own weapon (within a cone). RE: how stock riders that
   can shoot work (VS copilot / outside riders).
7. **Animations per seat** (sit, gunner stance, getting in / out): rMotionList work (lp2_blender_anim.py).

Suggested start: 3 (no game needed) alongside the RE spikes for 1 (host class + seats) and 2 (move test).

## Tuning knobs (jeep.h Params)
topSpeed, driveForce, grip / highSpeedGrip, rearSlideGrip, maxSteer / highSpeedSteer, springRate / damping /
antiRoll (0 = derived), centreOfMass, airPitch / airRoll / levelling, runOverMin / Knock / Kill.
