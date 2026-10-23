# Weapon workbench (idea, 2026-10-23): findings so far
- Weapon archives (uWpXX.arc) hold model / effects / sound only; stats are in exe data, registered by name at start
  (FUN_00cc8b10): "WpXXParam[SINGLE|ONLINE|ENEMY]" (0x54-byte struct, fields from FUN_00f5dd90: Status, FirePoint,
  IsShootType, ShootNum, ShootInterval, Range, LockRange, Durability(Max), DestructionLevel, BulletNum, BulletReload,
  BulletMax, ReloadTime, TargetShake, AccuracyArea(M), MuzzleAccuracyArea, Reaction, VibValue[2], VibTime, VibLevel,
  ZoomType, RespawnTimer, ShotCost, StrikeType) and "WpXXShellHitParam[n]" (FUN_00f5e830: Point (damage),
  ShrinkPoint / BlownPoint (stumble / knockdown), HitStopTimer, HitBackTimer, HitBackSpeed, MutekiTimer,
  CriticalRatio, Attribute[2], DestructionLevel, DecPowerRatio, ElectricPoint, HeadRate, PartsRate).
- Names: MsgCommon (ID_FCORE_EN_PC.arc) block 1; unused name slots a43-a65, a91-a100. Descriptions: MsgCinesco.
- Plan: mod weapon = JSON (base weapon class, stat overrides, name, model / textures) in a package; DLL maps a new id
  to the base class + its own param copies; packages already sync between players. Not started.
