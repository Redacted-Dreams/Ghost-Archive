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
   - Tails the local VRChat output log, parses ghost snapshot lines, and keeps the full archive in a **local** json (never committed).
   - `--bake` writes the whole archive as base files that are imported into the world and shipped with it.
   - Publishes only ghosts captured **since the last bake** to **GitHub Pages** (separate data repo, force-pushed, no history), which is the live layer the world reads from.
   - Rule: **first pose per display name wins forever.** A returning player does not overwrite their ghost.

3. **Playback (Unity shader, in-world)**
   - Archive is two **pose textures** (bone positions encoded in a texture): the baked base, plus new ghosts fetched from GitHub Pages at runtime.
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
- No opt-out in this system. Opt-out is handled by a separate, unconnected system. No opt-out list, no tombstones.
- Capture logs only on the scribe account's client (`scribeDisplayName` check in `GhostCapture`).
- Base archive (player list + poses) is baked into the world on normal publishes. GitHub Pages serves only ghosts captured since the last bake. No scheduled republishing.
- Archive source data stays local on the scribe machine. Neither this repo nor the data repo holds the full archive; the data repo keeps no history (single force-pushed commit).
- TSV v2 adds a `base` line; pose layout unchanged. Rows are fixed at first capture and never move.

## Planned extension — animated ghosts

Agreed direction, not yet built:
- v2 format: 1.5-second clips at 10 fps, frames across texture width, frame 0 == v1 static pose.
- A rotating roster of **five active animated ghosts** at a time; the rest stay static.
- Frame-lerped bone directions between clip frames.

## Current status

- v0.1 source is in this repo exactly as delivered (originally `Downloads\ghostarchive`). The **V2 files are current**: `GhostCaptureV2`, `GhostLoaderV2`, `GhostArchiveV3.shader`, `ghost_scribe_v2.py` (base + new split, no opt-out, scribe-only capture, `DisableBatching`; V3 shader adds foot grounding). v1 files are kept for reference; `GhostOptOut.cs` is retired. **Nothing has been compiled or brought up in Unity.** Expect UdonSharp API mismatches against the installed SDK; see `docs/CLAUDE_ghosts.md` for the list of calls to verify.
- `docs/CLAUDE_ghosts.md` is the sequenced bring-up plan (compile check → mock data → rig → mesh build → render test → loader → capture). Follow it in order, stop and report after each step.
- `docs/POSE_FORMAT.md` is the data contract (log line format, pose texture layout, TSV). **Do not change the log line format or pose layout.**
- README.md lists things the original author could not verify (PNG bit-exactness through `VRCImageDownloader`, `GetAvatarEyeHeightAsMeters`, the 180° `rotateFromTo` edge case, large-TSV string ops in Udon). The `rotateFromTo` math is now verified by `tools/shader_ref.py`; GPU behaviour still needs a device check. Treat these as the first things to test.
- The `choir` Unity project at `C:\Users\Nicho\AppData\Local\VRChatCreatorCompanion\VRChatProjects\choir` is **read-only**. Nothing is modified or deleted there unless Nick says so explicitly. This repo is where the work happens; importing into choir is a separate, later step.

## Repo layout

```
ghost-archive/
  unity/
    Udon/        GhostCaptureV2.cs (trigger → random capture → Debug.Log line, scribe client only)
                 GhostLoaderV2.cs  (baked base + new ghosts from Pages, drives material)
                 GhostCapture.cs, GhostLoader.cs, GhostOptOut.cs (v1, as delivered — not used)
    Editor/      GhostMeshBuilder.cs (bakes N rig copies into one mesh; regenerates GhostRig.cginc)
    Shaders/     GhostArchiveV3.shader (two pose textures, pose-texture skinning, foot grounding, age dither)
                 GhostArchive.shader, GhostArchiveV2.shader (older versions — not used)
                 GhostRig.cginc        (rig constants — generated; generic default checked in)
  scribe/        ghost_scribe_v2.py (tails VRChat log → local archive → bake / publish new → force push)
                 ghost_scribe.py    (v1, as delivered — not used)
                 .state/ghosts.json (local archive, gitignored — back this up, it is the only copy)
  tools/         shader_ref.py (CPU mirror of the current shader's vertex math; run after any shader/format change)
  docs/          CLAUDE_ghosts.md (bring-up plan), POSE_FORMAT.md (the contract)
  README.md      v0.1 overview, bring-up order, unverified items, not-in-v0.1 list
  CLAUDE.md      this file
```

Off-device shader check: `python tools/shader_ref.py` (split, pose round trip, grounding, rotateFromTo). Must stay ALL PASS.
Mock data: `python scribe/ghost_scribe_v2.py --mock 200 --out ./mock` writes base + new test files with no VRChat.
Bake cycle: stop scribe → `--bake <Assets dir>` → publish world → start scribe (its first publish trims the data repo).
Data repo: a separate public repo with GitHub Pages on; the scribe's `--repo` is a local clone of it.
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
2. Which low-poly humanoid rig (≤400 tris, Humanoid, T-pose) will be the ghost mesh?
