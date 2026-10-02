# Ghost Archive — Format Spec v1 (TSV v2)

v2 changes (2026-10): TSV gains a `base` line and ghosts are split into a baked base and
a downloaded "new" set. Log line format and pose texture layout are **unchanged**. Opt-out and
`[GHOSTX]` tombstones are removed (opt-out is handled by a separate system).

## One decision to flag first
Bone **rotations** from `GetBoneRotation` are not portable between avatars: each avatar's
T-pose bone orientation is different, so the same world rotation means different limb
directions on different rigs. Bone **positions** are portable. We store positions
(hips-relative, height-normalised) and the shader uses only their **directions** — the
ghost rig keeps its own limb lengths, so nothing stretches. Twist about the limb axis is
lost; that is acceptable.

## Bone set (19, parents always have a lower index)
```
 0 Hips        (root)      10 RightUpperArm (9)
 1 Spine       (0)         11 RightLowerArm (10)
 2 Chest       (1)         12 RightHand     (11)
 3 Neck        (2)         13 LeftUpperLeg  (0)
 4 Head        (3)         14 LeftLowerLeg  (13)
 5 LeftShoulder(2)         15 LeftFoot      (14)
 6 LeftUpperArm(5)         16 RightUpperLeg (0)
 7 LeftLowerArm(6)         17 RightLowerLeg (16)
 8 LeftHand    (7)         18 RightFoot     (17)
 9 RightShoulder(2)
```
Missing bones (avatar lacks them) are written as `0,0,0` and the shader falls back to the
rest direction for that segment. If Hips or Head is missing the capture is discarded.

## Log line (written by Udon via Debug.Log)
Capture:
```
[GHOST1]|<name>|<utcUnixSeconds>|<heightMm>|<rootXmm>,<rootYmm>,<rootZmm>|<b0x>,<b0y>,<b0z>;<b1x>,...;<b18x>,<b18y>,<b18z>|<crc>
```
- Bone values are integer millimetres relative to Hips, in world orientation.
- `crc` = sum of char codes of everything between the tag and the final `|`, mod 65536.
- Name is the raw display name; `|` in names is replaced by `_` before logging.

## Archive files (written by the scribe)
Every ghost gets a fixed ghost index on first capture (0, 1, 2, … in capture order); it never moves.
The scribe writes two pairs of files with the same layout:

| files | contains | where |
|---|---|---|
| `poses_base.png` + `ghosts_base.tsv` | ghosts `0 .. baked-1` | baked into the world (`--bake`), shipped on publish |
| `poses.png` + `ghosts.tsv` | ghosts `baked ..` (new since last bake) | GitHub Pages data repo |

`*.tsv` — tab separated:
```
v	2
base	<first ghost index in this file>
name	captureDay	lastSeenDay	visits	row
```
`captureDay` = days since 2020-01-01 UTC. `row` = absolute ghost index; the PNG row is `row - base`.
In-world, ghost i reads the base texture if `i < baseCount`, otherwise the new texture at row `i - base`.

`*.png` — RGBA8, width 64, height = next power of two ≥ ghost count (min 64).
Each row is one ghost. Each 16-bit value spans two channels: **R=low byte, G=high byte**
for the first value in a pixel, **B=low, A=high** for the second.
```
px 0 : rootX, rootY      (world, unit = 8 mm, offset 32768 → ±262 m)
px 1 : rootZ, heightMm
px 2..39 : bone i occupies px (2+2i) = (x, y), px (3+2i) = (z, 0)
           value = mm + 32768  (1 mm resolution, ±32 m, hips-relative)
px 40: captureDay (16-bit), visits (R), flags (G)
```
The PNG must arrive bit-exact. Verify in-world that `VRCImageDownloader` does not
recompress; if it does, switch to a 2× redundant encoding (spec v2).

## Limits to design against
- 500 ghosts PC, 150 Quest rendered; archive itself is unbounded.
- Combined mesh: keep ≤ 65k verts per mesh on Quest (16-bit indices).
