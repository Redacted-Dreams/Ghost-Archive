# Ghost Archive — CLAUDE.md

Standalone repo for the Ghost Archive system, split out of the Ashen Choir VRChat world (`choir` Unity project). This file is the handoff context for Claude Code sessions. Everything under "Locked" is settled — do not re-litigate; ask before changing.

## What it is

A pose-snapshot persistence system for VRChat. Players who visit the world leave a "ghost" behind: a frozen (later, briefly animated) silhouette of their pose, stored outside VRChat and streamed back into the world so later visitors see the accumulated presence of everyone who came before. Lore framing: the Ashen Choir's realm is where abandoned things collect — ghosts are the residue players leave in it.

## Architecture (as designed)

Three layers, one data flow:

1. **Capture (Unity / UdonSharp, in-world)**
   - Samples 19 humanoid bones per player.
   - Stores **positions, not rotations**, relative to the hips.
   - Cross-avatar portable: ghosts are scaled by **eye height only** (uniform), never proportional limb scaling — proportional scaling makes ghosts look goofy.
   - Emits the snapshot to the VRChat log (the only outbound channel Udon has).

2. **Scribe (Python, outside VRChat)** — `ghost_scribe.py`
   - Tails the local VRChat output log, parses ghost snapshot lines, and writes them to the archive data set.
   - Publishes that data set to **GitHub Pages**, which is the live layer the world reads from.
   - Rule: **first pose per display name wins forever.** A returning player does not overwrite their ghost.

3. **Playback (Unity shader, in-world)**
   - Archive is loaded as a **pose texture** (bone positions encoded in a texture) fetched from GitHub Pages at runtime.
   - All ghosts render in a **single draw call** via a pose-texture vertex shader.
   - **Bayer dither** encodes age-based presence: older ghosts are sparser/fainter, recent ones more solid.

## Locked decisions

- 19 humanoid bones, hips-relative positions.
- Positions only (no rotations).
- Uniform scale by eye height only.
- First-pose-per-display-name wins forever.
- Single draw call, pose-texture vertex shader, Bayer dither for age.
- GitHub Pages is the live data layer; `ghost_scribe.py` is the writer.
- Unity Built-in Render Pipeline. Target shader model 3.5 where MonoSH is involved.
- `DisableBatching="True"` on object-space procedural shaders.
- Never use `_RNM0`; use `unity_LightmapInd` for Bakery MonoSH.
- Every patched file gets a new version tail (e.g. `GhostShaderV3`), never edited in place under the same name.
- Must run on both PC and Quest.
- VRChat staff have confirmed in writing that the external bot/scribe setup is permissible.
- Opaque cutout + Bayer dither. No transparency.
- Opt-out model, not opt-in: `GhostOptOut` sets a PlayerData bool and writes a tombstone.
- Capture logs only on the scribe account's client (`scribeDisplayName` check in `GhostCapture`).
- Live archive is fetched from GitHub Pages at runtime; a baked native copy is the fallback, refreshed only on normal world publishes. No scheduled republishing.

## Planned extension — animated ghosts

Agreed direction, not yet built:
- v2 format: 1.5-second clips at 10 fps, frames across texture width, frame 0 == v1 static pose.
- A rotating roster of **five active animated ghosts** at a time; the rest stay static.
- Frame-lerped bone directions between clip frames.

## Current status

- v0.1 source is in this repo (originally delivered to `Downloads\ghostarchive`). **It has never been compiled or brought up in Unity.** Expect UdonSharp API mismatches against the installed SDK; see `docs/CLAUDE_ghosts.md` for the list of calls to verify.
- `docs/CLAUDE_ghosts.md` is the sequenced bring-up plan (compile check → mock data → rig → mesh build → render test → loader → capture). Follow it in order, stop and report after each step.
- `docs/POSE_FORMAT.md` is the data contract (log line format, pose texture layout, TSV). **Do not change the log line format or pose layout.**
- README.md lists things the original author could not verify (PNG bit-exactness through `VRCImageDownloader`, `PlayerData` signatures, `GetAvatarEyeHeightAsMeters`, the 180° `rotateFromTo` edge case, large-TSV string ops in Udon). Treat these as the first things to test.
- The `choir` Unity project at `C:\Users\Nicho\AppData\Local\VRChatCreatorCompanion\VRChatProjects\choir` is **read-only**. Nothing is modified or deleted there unless Nick says so explicitly. This repo is where the work happens; importing into choir is a separate, later step.

## Repo layout

```
ghost-archive/
  unity/
    Udon/        GhostCapture.cs (trigger → random capture → Debug.Log line)
                 GhostOptOut.cs  (PlayerData opt-out + tombstone)
                 GhostLoader.cs  (fetches poses.png + ghosts.tsv from Pages, drives material)
    Editor/      GhostMeshBuilder.cs (bakes N rig copies into one mesh; regenerates GhostRig.cginc)
    Shaders/     GhostArchive.shader (pose-texture skinning, age dither)
                 GhostRig.cginc      (rig constants — generated; generic default checked in)
  scribe/        ghost_scribe.py (tails VRChat log → archive → tsv/png → git push)
  pages/         GitHub Pages output: poses.png + ghosts.tsv (+ archive json)
  docs/          CLAUDE_ghosts.md (bring-up plan), POSE_FORMAT.md (the contract)
  README.md      v0.1 overview, bring-up order, unverified items, not-in-v0.1 list
  CLAUDE.md      this file
```

Mock data: `python scribe/ghost_scribe.py --repo ./pages --mock 200` generates test files with no VRChat.
Pose PNG import settings in Unity: sRGB off, compression none, point filter, mipmaps off, read/write off.

Long-term goal: this becomes a reusable VCC package (`com.ashenchoir.ghosts`) that drops into any world, not just choir.

## Related systems in the choir world (context only)

- `_AshenMadness` global float is the World-State Bus; ghost presence may eventually read from it.
- `NoiseVolume_128.asset` (Tools > Ashen Choir > Generate Noise Volume) is the shared noise source for other effects; not currently used by ghosts.
- Shader previews elsewhere in the project carry a live ops-feed overlay (ops/pixel, GPU ms, resolution) and two 8s record buttons — if a ghost shader preview widget is built, match that convention.

## How Nick works

- Simpler and cleaner wins. He consistently corrects overbuilt or overly literal interpretations — confirm aesthetic direction before adding complexity.
- Give options with a clear recommendation and the reasoning, not open-ended questions.
- Iterate in small steps with explicit pass/fail checkpoints, not large speculative builds.
- Hold prior decisions firmly; don't re-open settled ones.
- He catches internal inconsistencies and expects a redesign in response.
- End responses with concise, targeted questions.
- Deliver context docs (CLAUDE_*.md) as handoff artifacts when a session produces something the next one needs.

## Open questions

1. Does the scribe run on Nick's machine only, or should it be packaged for a second host?
2. GitHub Pages source: this repo's `pages/` folder (recommended — one repo), or a separate repo?
3. Which low-poly humanoid rig (≤400 tris, Humanoid, T-pose) will be the ghost mesh?
