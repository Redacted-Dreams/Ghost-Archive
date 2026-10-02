#!/usr/bin/env python3
"""
CPU reference of GhostArchiveV3.shader's vertex path (pose decode, re-pose, grounding, base/new split).
Checks the shader math off-device, with no Unity. Keep it in step with the current shader version.

  python tools/shader_ref.py        prints PASS/FAIL per check, exit code 1 on any failure

Requires: pillow. Uses scribe/ghost_scribe_v2.py to write the test PNGs, so the data path is real.
"""
import math, random, re, sys, tempfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scribe"))
import ghost_scribe_v2 as gs
from PIL import Image

# ---------------------------------------------------------------- rig constants from GhostRig.cginc
cg = (REPO / "unity/Shaders/GhostRig.cginc").read_text()
EYE = float(re.search(r"GHOST_RIG_EYE_HEIGHT\s+([\d.]+)", cg).group(1))
REST = [tuple(float(x) for x in m) for m in re.findall(r"float3\(\s*([-\d.]+),\s*([-\d.]+),\s*([-\d.]+)\)", cg)]
PARENT = [int(x) for x in re.search(r"GHOST_PARENT\[GHOST_BONES\] = \{([^}]*)\}", cg).group(1).split(",")]
assert len(REST) == 19 and len(PARENT) == 19

def sub(a, b): return tuple(x - y for x, y in zip(a, b))
def add(a, b): return tuple(x + y for x, y in zip(a, b))
def mulv(a, s): return tuple(x * s for x in a)
def dot(a, b): return sum(x * y for x, y in zip(a, b))
def length(a): return math.sqrt(dot(a, a))
def norm(a): return mulv(a, 1 / length(a))
def cross(a, b): return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])

# ---------------------------------------------------------------- shader mirror
class Mat:
    """Material uniforms, as GhostLoaderV2 sets them."""
    def __init__(self, base_png, base_count, new_png, new_start, ghost_count, today):
        def load(p):
            if not p: return None, 64
            im = Image.open(p).convert("RGBA"); return im.load(), im.height
        self.base, self.base_rows = load(base_png)
        self.new, self.new_rows = load(new_png)
        self.base_count, self.new_start, self.ghost_count, self.today = base_count, new_start, ghost_count, today

def read2(tex, px, row):
    r, g, b, a = tex[px, row] if tex else (0, 0, 0, 0)
    return (r + g * 256, b + a * 256)

def vert_ghost(m, idx):
    """Joint world positions for ghost idx, or None where the shader collapses it."""
    is_new = idx >= m.base_count
    row = idx - m.new_start if is_new else idx
    rows = m.new_rows if is_new else m.base_rows
    if idx >= m.ghost_count or row < 0 or row >= rows:
        return None
    tex = m.new if is_new else m.base
    p0, p1 = read2(tex, 0, row), read2(tex, 1, row)
    if p1[1] < 1:
        return None
    root = mulv(sub((p0[0], p0[1], p1[0]), (32768,) * 3), 0.008)
    scale = max(0.2, p1[1] * 0.001 / EYE)
    P = []
    for b in range(19):
        xy, z0 = read2(tex, 2 + 2 * b, row), read2(tex, 3 + 2 * b, row)
        P.append(mulv(sub((xy[0], xy[1], z0[0]), (32768,) * 3), 0.001))
    N = [(0, 0, 0)]
    for j in range(1, 19):
        par = PARENT[j]
        d_rest, d_cap = sub(REST[j], REST[par]), sub(P[j], P[par])
        missing = dot(P[j], P[j]) < 1e-8 or dot(d_cap, d_cap) < 1e-6
        N.append(add(N[par], mulv(norm(d_rest) if missing else norm(d_cap), length(d_rest))))
    cap_foot = ghost_foot = 1e5
    for f in (15, 18):
        if dot(P[f], P[f]) > 1e-8:
            cap_foot, ghost_foot = min(cap_foot, P[f][1]), min(ghost_foot, N[f][1] * scale)
    lift = cap_foot - ghost_foot if cap_foot < 1e4 else 0
    return [add(add(root, mulv(n, scale)), (0, lift, 0)) for n in N], scale

def rotate_from_to(v, a, b):
    axis = cross(a, b); s2 = dot(axis, axis); c = dot(a, b)
    if s2 < 1e-8:
        if c > 0: return v
        p = (0, 1, 0) if abs(a[1]) < 0.9 else (1, 0, 0)
        axis = norm(cross(a, p))
        return sub(mulv(axis, 2 * dot(v, axis)), v)
    s = math.sqrt(s2); k = mulv(axis, 1 / s)
    return add(add(mulv(v, c), mulv(cross(k, v), s)), mulv(k, dot(k, v) * (1 - c)))

# ---------------------------------------------------------------- helpers
TODAY = (datetime.now(timezone.utc) - gs.EPOCH_2020).days
FAILS = []

def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}")
    if not ok: FAILS.append(label)

def one_ghost(tmp, joints, hips_world, eye_h, name="t"):
    """Push one capture through the real log-line parser and PNG writer; return its material."""
    root = [round(c * 1000) for c in hips_world]
    bones = [[round(c * 1000) for c in v] for v in joints]
    body = f"{name}|1759300000|{round(eye_h * 1000)}|{','.join(map(str, root))}|" + \
           ";".join(",".join(map(str, b)) for b in bones)
    ev = gs.parse_line(f"[GHOST1]|{body}|{gs.crc(body)}")
    assert ev, "parse failed"
    a = gs.Archive(Path("/nonexistent")); a.apply(ev); a.baked = 1
    out = Path(tmp) / name; a.write_base(out)
    return Mat(out / "poses_base.png", 1, None, 1, 1, TODAY)

def rot(v, ax, ang):
    ax = norm(ax); c, s = math.cos(ang), math.sin(ang)
    return add(add(mulv(v, c), mulv(cross(ax, v), s)), mulv(ax, dot(ax, v) * (1 - c)))

# ---------------------------------------------------------------- checks
def main():
    with tempfile.TemporaryDirectory() as tmp:
        print("base/new split (mock: 160 base + 40 new)")
        a = gs.Archive(Path("/nonexistent")); gs.mock(a, 200); a.baked = 160
        a.write_base(Path(tmp)); a.write_new(Path(tmp))
        bp, np_ = Path(tmp) / "poses_base.png", Path(tmp) / "poses.png"
        for label, bc, ns, gc, exp in [("normal", 160, 160, 200, 200),
                                       ("_BaseCount=0 draws only new", 0, 160, 200, 40),
                                       ("gap (data trimmed before world update)", 160, 170, 210, 200),
                                       ("overlap (world newer than data)", 160, 150, 190, 190)]:
            m = Mat(bp, bc, np_, ns, gc, TODAY)
            n = sum(1 for i in range(gc) if vert_ghost(m, i))
            check(label, n == exp, f"drawn {n}, expected {exp}")

        print("pose round trip (log line -> scribe PNG -> shader decode -> re-pose)")
        big = [mulv(r, 1.25) for r in REST]
        J = [(0, 0, 0)] * 19
        for j in range(1, 19):
            d = sub(big[j], big[PARENT[j]])
            if j in (6, 7, 8, 10, 11, 12): d = (0, -length(d), 0)   # arms hanging
            if j in (17, 18): d = rot(d, (1, 0, 0), -1.2)           # right leg kicked forward
            if j <= 12: d = rot(d, (1, 0, 0), 0.25)                 # upper body leans
            J[j] = add(J[PARENT[j]], d)
        hips = (1.5, 1.1, -2.0)
        Jg, scale = vert_ghost(one_ghost(tmp, J, hips, 1.6 * 1.25, "pose"), 0)
        worst = max(math.degrees(math.acos(max(-1, min(1, dot(norm(sub(J[j], J[PARENT[j]])),
                                                              norm(sub(Jg[j], Jg[PARENT[j]]))))))) for j in range(1, 19))
        check("bone directions", worst < 0.5, f"worst {worst:.3f} deg")
        check("uniform scale by eye height", abs(scale - 1.25) < 1e-3, f"{scale:.3f}")

        print("grounding (lowest ghost foot = lowest captured foot)")
        for k, label in [(1.0, "rig proportions"), (1.25, "long legs +25%"), (0.8, "short legs -20%")]:
            bones = [list(r) for r in REST]
            for j in (13, 14, 15, 16, 17, 18): bones[j][1] *= k
            hips_y = -bones[15][1]  # feet on y=0
            Jg, _ = vert_ghost(one_ghost(tmp, bones, (0, hips_y, 0), EYE, f"leg{k}"), 0)
            foot = min(Jg[15][1], Jg[18][1])
            check(label, abs(foot) < 0.01, f"foot at {foot * 100:+.1f} cm")
        bones = [list(r) for r in REST]; bones[18] = [0, 0, 0]  # one foot missing
        Jg, _ = vert_ghost(one_ghost(tmp, bones, (0, -REST[15][1], 0), EYE, "onefoot"), 0)
        check("one foot missing", abs(Jg[15][1]) < 0.01, f"foot at {Jg[15][1] * 100:+.1f} cm")

        print("rotateFromTo")
        random.seed(1)
        rnd = lambda: norm((random.gauss(0, 1), random.gauss(0, 1), random.gauss(0, 1)))
        cases = [((0, 1, 0), (0, -1, 0)), ((1, 0, 0), (-1, 0, 0)), ((0, .95, .3122), (0, -.95, -.3122))] + \
                [(rnd(), rnd()) for _ in range(2000)]
        err, mirror = 0, False
        for a_, b_ in cases:
            a_, b_ = norm(a_), norm(b_)
            err = max(err, length(sub(rotate_from_to(a_, a_, b_), b_)), abs(length(rotate_from_to(rnd(), a_, b_)) - 1))
            x, y, z = (rotate_from_to(e, a_, b_) for e in ((1, 0, 0), (0, 1, 0), (0, 0, 1)))
            mirror |= dot(x, cross(y, z)) < 0
        check("maps a to b, keeps length, incl. 180 deg", err < 1e-6, f"worst {err:.1e}")
        check("never mirrors", not mirror)

    print("ALL PASS" if not FAILS else f"{len(FAILS)} FAILED: {', '.join(FAILS)}")
    sys.exit(1 if FAILS else 0)

if __name__ == "__main__":
    main()
