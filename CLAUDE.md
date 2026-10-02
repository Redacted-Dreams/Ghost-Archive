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

## Planned extension — animated ghosts

Agreed direction, not yet built:
- 1.5-second pose clips instead of single frames.
- A rotating roster of **five active animated ghosts** at a time; the rest stay static.
- Frame-lerped bone directions between clip frames.

## Current status

- Nine files were delivered in an earlier session (Unity capture scripts, shader, scribe, Pages layer, and `CLAUDE_ghosts.md` with sequenced bring-up steps). **They have not been brought up in Unity yet.** Locate those files first (choir project `Assets`, `ChoirBackups`, or Downloads) before writing anything new — the originals are the source of truth and this repo should start from them, not from a rewrite.
- `CLAUDE_ghosts.md` contains the bring-up sequence. Follow it in order with a pass/fail check at each step.
- The `choir` Unity project at `C:\Users\Nicho\AppData\Local\VRChatCreatorCompanion\VRChatProjects\choir` is **read-only**. Nothing is modified or deleted there unless Nick says so explicitly. This repo is where the work happens; importing into choir is a separate, later step.

## Repo layout

```
ghost-archive/
  unity/
    Runtime/     UdonSharp capture + playback behaviours
    Shaders/     pose-texture vertex shader (+ Quest variant)
    Editor/      any editor tooling (pose-texture baker, etc.)
  scribe/        ghost_scribe.py + requirements
  pages/         GitHub Pages site: published archive data
  docs/          CLAUDE_ghosts.md and design notes
  CLAUDE.md      this file
```

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

## Open questions (answer before building)

1. Where do the nine delivered files currently live on disk?
2. Does the scribe run on Nick's machine only, or should it be packaged for a second host?
3. What is the GitHub Pages repo/branch for the live data — this repo's `pages/` via Pages, or a separate repo?
