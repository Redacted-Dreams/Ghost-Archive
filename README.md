# Ghost Archive v0.1

Persistent ghosts of past visitors: one pose, one name, one date, rendered in a single draw call.

```
Udon/GhostCapture.cs      trigger volume → random capture → Debug.Log line
Udon/GhostOptOut.cs       PlayerData opt-out + tombstone
Udon/GhostLoader.cs       fetches poses.png + ghosts.tsv from github.io, drives material
Scribe/ghost_scribe.py    tails VRChat log → archive → tsv/png → git push
Editor/GhostMeshBuilder.cs bakes N rig copies into one mesh; regenerates GhostRig.cginc
Shaders/GhostArchive.shader  pose-texture skinning, age dither
Shaders/GhostRig.cginc    rig constants (generated; generic default included)
POSE_FORMAT.md            the contract
```

## Bring-up order
1. **Mock data first.** `python ghost_scribe.py --repo ./pages --mock 200` writes test files with no VRChat.
2. Import a low-poly humanoid rig (Animator set to Humanoid, T-pose, at origin, feet on y=0).
   Open **AshenChoir > Ghost Mesh Builder**, build 200 copies. It rewrites `GhostRig.cginc`.
3. Put the mesh on a GameObject at the world origin with the `AshenChoir/GhostArchive` material.
4. Assign the mock `poses.png` (import: **sRGB off, no compression, point filter, no mips**)
   and `ghosts.tsv` as the loader's fallbacks. Set `_GhostCount` and `_TodayDay` by hand or via loader.
   You should see 200 posed ghosts. Fix the shader here, in editor, before touching VRChat.
5. Create a GitHub Pages repo, push the mock files, point the loader's VRCUrls at it.
6. Add `GhostCapture` on a trigger volume, `GhostOptOut` on a switch, a notice at spawn.
7. Run the scribe on the bot machine: `python ghost_scribe.py --repo ./pages --replay`.

## Things I could not verify from here — check on device first
- **PNG bit-exactness through `VRCImageDownloader`.** If values come back wrong, flip `_LinearizeSRGB`
  first; if still wrong the downloader is compressing and we go to a redundant encoding (v2).
- `PlayerData.TryGetBool(player, key, out v)` signature and `OnPlayerRestored` — match to your SDK version.
- `GetAvatarEyeHeightAsMeters` exists in recent SDKs; older ones need a bone-based estimate.
- The shader's 180° edge case in `rotateFromTo` and hips basis when legs are stacked (sitting cross-legged).
- Udon string ops on a large TSV: fine to a few hundred rows, spread across frames beyond that.

## Not in v0.1
Name labels on proximity, in-instance instant preview of your own ghost, shadow caster pass,
Quest material variant, moderation UI (blocklist is a JSON field for now), reaction-map haunt channel.
