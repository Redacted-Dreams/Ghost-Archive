# CLAUDE_ghosts.md — Ghost Archive wiring session

Project: `C:\Users\Nicho\AppData\Local\VRChatCreatorCompanion\VRChatProjects\choir`
Unity Built-in RP, VRChat Worlds SDK, UdonSharp. Read `CLAUDE.md` and `CLAUDE_shaders_2.md` first for project conventions.

## Goal of this session
Get the Ghost Archive rendering in the editor from mock data, then compiling in Udon. No VRChat upload yet.

## Source files (copy in from the GhostArchive delivery folder)
```
Assets/GhostArchive/Udon/GhostCapture.cs
Assets/GhostArchive/Udon/GhostOptOut.cs
Assets/GhostArchive/Udon/GhostLoader.cs
Assets/GhostArchive/Editor/GhostMeshBuilder.cs
Assets/GhostArchive/Shaders/GhostArchive.shader
Assets/GhostArchive/Shaders/GhostRig.cginc        (generic default; builder regenerates)
Tools/ghost_scribe.py                              (outside Assets/)
docs/POSE_FORMAT.md
```

## Steps, in order — stop and report after each
1. **Compile check.** Import the three Udon scripts and the editor script. Fix any UdonSharp API mismatches
   against the installed SDK version. Known things to verify: `PlayerData.TryGetBool(VRCPlayerApi, string, out bool)`,
   `OnPlayerRestored`, `GetAvatarEyeHeightAsMeters`, `VRCImageDownloader.DownloadImage(VRCUrl, Material, IUdonEventReceiver, TextureInfo)`,
   `VRCStringDownloader.LoadUrl`. Do not change the log line format or the pose layout — those are the contract.
2. **Mock data.** `python Tools/ghost_scribe.py --repo Tools/pages --mock 200`. Import `Tools/pages/poses.png`
   into `Assets/GhostArchive/Mock/` with: sRGB **off**, compression **none**, filter **point**, mipmaps **off**,
   read/write off. Import `ghosts.tsv` as a TextAsset (rename to `ghosts_tsv.txt` if needed).
3. **Rig.** Find or make a low-poly humanoid (≤400 tris). Requirements: Animator avatar set to Humanoid,
   T-pose, transform identity, feet on y=0, single SkinnedMeshRenderer. Place in a `GhostRig` scene.
4. **Build mesh.** `AshenChoir > Ghost Mesh Builder`, 200 copies, 16-bit indices. Confirm it rewrites
   `GhostRig.cginc` with real rest positions and eye height.
5. **Render test.** Empty GameObject `GhostArchive` at world origin, MeshFilter = built mesh, MeshRenderer with
   material `M_GhostArchive` (shader `AshenChoir/GhostArchive`). Set `_PoseTex` = mock png, `_PoseRows` = png height,
   `_GhostCount` = 200, `_TodayDay` = (days since 2020-01-01 UTC, compute today), `_LinearizeSRGB` = 0 for the
   editor-imported texture. Expect 200 posed humanoids scattered ±6 m. If limbs are wrong, debug in this order:
   pixel decode (`read2`) → root/height → direction chain → per-bone rotation. Render a single ghost by setting
   `_GhostCount` = 1.
6. **Loader.** Add `GhostLoader` to the GhostArchive object, assign renderer and the mock png/tsv as fallbacks.
   Leave URLs empty for now; confirm fallback path renders in play mode without errors.
7. **Capture.** Trigger volume with `GhostCapture`. In ClientSim, walk in, wait past `minDelay`, confirm a
   `[GHOST1]|...` line appears in the console with 19 bone triples and a valid crc
   (verify with `python Tools/ghost_scribe.py` parse — add a `--check "<line>"` flag if useful).

## Decisions already made — do not relitigate
- Positions, not rotations (cross-avatar portability). Directions only; rig keeps its own limb lengths.
- No proportional scaling. Uniform scale by captured eye height only.
- Opaque cutout + Bayer dither. No transparency.
- First pose per display name wins. Opt-out is a PlayerData bool + tombstone, opt-out model not opt-in.
- Capture logs only on the scribe account's client (add `scribeDisplayName` check to `GhostCapture` if not present:
  `if (!Networking.LocalPlayer.displayName.Equals(scribeDisplayName)) return;` before Debug.Log).
- Live archive is fetched from GitHub Pages; native copy is a baked fallback refreshed only on normal publishes.
  No scheduled world republishing.

## Next after this session (not now)
- v2 format: 1.5 s clips at 10 fps, frames across texture width, frame 0 == v1 static pose.
- Roster: Udon picks ≤5 active ghosts, passes indices + start times to the material; fade in/out via dither over clip time.
- Proximity name labels, shadow-caster pass, Quest variant, reaction-map haunt channel.
