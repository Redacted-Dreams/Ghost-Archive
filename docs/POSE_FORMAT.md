# Ghost Archive — Format Spec v1

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
Tombstone (opt-out):
```
[GHOSTX]|<name>|<utcUnixSeconds>|<crc>
```
- Bone values are integer millimetres relative to Hips, in world orientation.
- `crc` = sum of char codes of everything between the tag and the final `|`, mod 65536.
- Name is the raw display name; `|` in names is replaced by `_` before logging.

## Archive files (written by the scribe, served from GitHub Pages)
`ghosts.tsv` — one row per ghost, tab separated, header row first:
```
v	1
name	captureDay	lastSeenDay	visits	row
```
`captureDay` = days since 2020-01-01 UTC. `row` = row index in `poses.png`.

`poses.png` — RGBA8, width 64, height = next power of two ≥ ghost count (min 64).
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

## Opt-out
- `PlayerData` bool key `ghost_optout`. Checked before every capture and on restore.
- Toggling on logs a tombstone. Scribe deletes the record and rewrites both files.
- Toggling off resumes capture on the *next* visit (no retroactive capture).

## Limits to design against
- 500 ghosts PC, 150 Quest rendered; archive itself is unbounded.
- Combined mesh: keep ≤ 65k verts per mesh on Quest (16-bit indices).
