# CLAUDE_ghosts.md — Ghost Archive wiring session

Project: `C:\Users\Nicho\AppData\Local\VRChatCreatorCompanion\VRChatProjects\choir`
Unity Built-in RP, VRChat Worlds SDK, UdonSharp. Read `CLAUDE.md` and `CLAUDE_shaders_2.md` first for project conventions.

## Goal of this session
Get the Ghost Archive rendering in the editor from mock data, then compiling in Udon. No VRChat upload yet.

## Source files (copy in from this repo — V2 files only)
```
Assets/GhostArchive/Udon/GhostCaptureV2.cs
Assets/GhostArchive/Udon/GhostLoaderV2.cs
Assets/GhostArchive/Editor/GhostMeshBuilder.cs
Assets/GhostArchive/Shaders/GhostArchiveV2.shader
Assets/GhostArchive/Shaders/GhostRig.cginc        (generic default; builder regenerates)
Tools/ghost_scribe_v2.py                           (outside Assets/)
docs/POSE_FORMAT.md
```
Do this in a scratch test project first, not choir (choir is read-only).

## Steps, in order — stop and report after each
1. **Compile check.** Import the two Udon scripts, the editor script and the shader. Fix any UdonSharp API mismatches
   against the installed SDK version. Known things to verify: `GetAvatarEyeHeightAsMeters`, `VRCImageDownloader.DownloadImage(VRCUrl, Material, IUdonEventReceiver, TextureInfo)`,
   `VRCStringDownloader.LoadUrl`. Do not change the log line format or the pose layout — those are the contract.
2. **Mock data.** `python Tools/ghost_scribe_v2.py --mock 200 --out Tools/mock` (160 base + 40 new). Import both PNGs
   into `Assets/GhostArchive/Mock/` with: sRGB **off**, compression **none**, filter **point**, mipmaps **off**,
   read/write off. Import both TSVs as TextAssets (rename to `.txt` if needed).
3. **Rig.** Find or make a low-poly humanoid (≤400 tris). Requirements: Animator avatar set to Humanoid,
   T-pose, transform identity, feet on y=0, single SkinnedMeshRenderer. Place in a `GhostRig` scene.
4. **Build mesh.** `AshenChoir > Ghost Mesh Builder`, 200 copies, 16-bit indices. Confirm it rewrites
   `GhostRig.cginc` with real rest positions and eye height.
5. **Render test.** Empty GameObject `GhostArchive` at world origin, MeshFilter = built mesh, MeshRenderer with
   material `M_GhostArchive` (shader `AshenChoir/GhostArchiveV2`). Set `_PoseTex` = `poses_base.png`, `_PoseRows` = its height,
   `_BaseCount` = 160, `_PoseTexNew` = mock `poses.png`, `_PoseRowsNew` = its height, `_NewStart` = 160, `_GhostCount` = 200,
   `_TodayDay` = (days since 2020-01-01 UTC, compute today), `_LinearizeSRGB` = 0 and `_LinearizeSRGBNew` = 0 for
   editor-imported textures. Expect 200 posed humanoids scattered ±6 m. Then set `_BaseCount` = 0: expect only the 40 new
   ghosts; indices 0–159 fall before `_NewStart` and are not drawn. This proves the split and the gap handling. If limbs are wrong, debug in this order:
   pixel decode (`read2`) → root/height → direction chain → per-bone rotation. Render a single ghost by setting
   `_GhostCount` = 1.
6. **Loader.** Add `GhostLoaderV2` to the GhostArchive object, assign renderer and the mock base png/tsv.
   Leave URLs empty for now; confirm the base renders (160 ghosts) in play mode without errors.
7. **Capture.** Trigger volume with `GhostCaptureV2`, `scribeDisplayName` = the ClientSim player's name. In ClientSim,
   walk in, wait past `minDelay`, confirm a `[GHOST1]|...` line appears in the console with 19 bone triples and a valid
   crc: `python Tools/ghost_scribe_v2.py --check "<line>"`. Then clear `scribeDisplayName` and confirm nothing is logged.

## Decisions already made — do not relitigate
- Positions, not rotations (cross-avatar portability). Directions only; rig keeps its own limb lengths.
- No proportional scaling. Uniform scale by captured eye height only.
- Opaque cutout + Bayer dither. No transparency.
- First pose per display name wins. No opt-out in this system (handled separately).
- Capture logs only on the scribe account's client (`scribeDisplayName` in `GhostCaptureV2`).
- Base archive is baked into the world on normal publishes; GitHub Pages serves only ghosts since the last bake.
  No scheduled world republishing. Archive json stays local to the scribe machine.

## Next after this session (not now)
- v2 format: 1.5 s clips at 10 fps, frames across texture width, frame 0 == v1 static pose.
- Roster: Udon picks ≤5 active ghosts, passes indices + start times to the material; fade in/out via dither over clip time.
- Proximity name labels, shadow-caster pass, Quest variant, reaction-map haunt channel.
