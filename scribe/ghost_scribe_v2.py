#!/usr/bin/env python3
"""
Ghost Archive scribe v2.

Tails the newest VRChat output log on this machine, parses [GHOST1] lines, and keeps the
full archive in a LOCAL json file (never committed anywhere).

Ghosts are split in two:
  base  - every ghost up to the last --bake. Written as poses_base.png + ghosts_base.tsv,
          imported into the world and shipped with it on a normal publish.
  new   - ghosts captured since the last bake. Written as poses.png + ghosts.tsv into the
          GitHub Pages data repo and force-pushed as a single commit (no history kept).

Usage:
  python ghost_scribe_v2.py --repo /path/to/pages-data-repo [--log-dir ...] [--push-every 60]
  python ghost_scribe_v2.py --bake /path/to/unity/Assets/GhostArchive/Baked   (scribe stopped)
  python ghost_scribe_v2.py --mock 200 --out ./mock
  python ghost_scribe_v2.py --check "<log line>"

Requires: pillow. git must be configured with push credentials for the data repo.
"""
import argparse, glob, json, os, re, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    sys.exit("pip install pillow")

BONES = 19
PNG_W = 64
EPOCH_2020 = datetime(2020, 1, 1, tzinfo=timezone.utc)
DEFAULT_ARCHIVE = Path(__file__).resolve().parent / ".state" / "ghosts.json"

LINE_RE = re.compile(r"\[GHOST1\]\|(.*)$")

# ----------------------------------------------------------------------------- parsing

def crc(s: str) -> int:
    return sum(ord(c) for c in s) & 0xFFFF

def parse_line(line: str):
    m = LINE_RE.search(line)
    if not m:
        return None
    rest = m.group(1).rstrip("\r\n")
    body, sep, crc_s = rest.rpartition("|")
    if not sep or not crc_s.isdigit() or crc(body) != int(crc_s):
        return None
    f = body.split("|")
    try:
        name, ts, height = f[0], int(f[1]), int(f[2])
        root = [int(v) for v in f[3].split(",")]
        bones = [[int(v) for v in b.split(",")] for b in f[4].split(";")]
        if len(root) != 3 or len(bones) != BONES or any(len(b) != 3 for b in bones):
            return None
        if not (300 <= height <= 6000):
            return None
        return {"name": name, "ts": ts, "height": height, "root": root, "bones": bones}
    except (ValueError, IndexError):
        return None

def day_of(ts: int) -> int:
    return int((datetime.fromtimestamp(ts, timezone.utc) - EPOCH_2020).days)

# ----------------------------------------------------------------------------- archive

class Archive:
    """name -> record. Each record has a fixed 'row' assigned on first capture, so rows
    already baked into the world never move."""

    def __init__(self, path: Path):
        self.path = path
        self.ghosts = {}
        self.blocklist = set()    # moderation: names never captured
        self.baked = 0            # rows [0, baked) are shipped in the world
        self.dirty = False
        if path.exists():
            d = json.loads(path.read_text(encoding="utf-8"))
            self.ghosts = d.get("ghosts", {})
            self.blocklist = set(d.get("blocklist", []))
            self.baked = d.get("baked", 0)
            if any("row" not in g for g in self.ghosts.values()):
                # v1 archive: assign rows in v1 export order (oldest first)
                for i, (_, g) in enumerate(sorted(self.ghosts.items(), key=lambda kv: (kv[1]["ts"], kv[0]))):
                    g["row"] = i

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "v": 2,
            "baked": self.baked,
            "ghosts": self.ghosts,
            "blocklist": sorted(self.blocklist),
        }, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def apply(self, ev):
        name = ev["name"]
        if name in self.blocklist:
            return False
        day = day_of(ev["ts"])
        if name in self.ghosts:
            g = self.ghosts[name]
            if day > g["lastSeenDay"]:
                g["visits"] += 1
                g["lastSeenDay"] = day
                self.dirty = True
            return False  # first pose wins
        self.ghosts[name] = {
            "row": len(self.ghosts),
            "captureDay": day, "lastSeenDay": day, "visits": 1,
            "height": ev["height"], "root": ev["root"], "bones": ev["bones"],
            "ts": ev["ts"],
        }
        self.dirty = True
        return True

    def rows(self, lo, hi=None):
        """Records with lo <= row < hi, in row order."""
        out = [(n, g) for n, g in self.ghosts.items() if g["row"] >= lo and (hi is None or g["row"] < hi)]
        return sorted(out, key=lambda kv: kv[1]["row"])

    # ---- export: same pose layout as POSE_FORMAT.md v1; TSV gains a 'base' line

    @staticmethod
    def write_tsv(out: Path, items, base: int):
        rows = ["v\t2", f"base\t{base}", "name\tcaptureDay\tlastSeenDay\tvisits\trow"]
        for name, g in items:
            rows.append(f"{name}\t{g['captureDay']}\t{g['lastSeenDay']}\t{g['visits']}\t{g['row']}")
        out.write_text("\n".join(rows) + "\n", encoding="utf-8")

    @staticmethod
    def write_png(out: Path, items, base: int):
        h = 64
        while h < len(items):
            h *= 2
        img = Image.new("RGBA", (PNG_W, h), (0, 0, 0, 0))
        px = img.load()

        def u16(v):
            return max(0, min(65535, int(v)))

        def put(x, y, a, b):
            a, b = u16(a), u16(b)
            px[x, y] = (a & 0xFF, a >> 8, b & 0xFF, b >> 8)

        for name, g in items:
            y = g["row"] - base
            rx, ry, rz = g["root"]
            put(0, y, rx // 8 + 32768, ry // 8 + 32768)
            put(1, y, rz // 8 + 32768, g["height"])
            for i, (bx, by, bz) in enumerate(g["bones"]):
                put(2 + 2 * i, y, bx + 32768, by + 32768)
                put(3 + 2 * i, y, bz + 32768, 0)
            put(40, y, g["captureDay"], min(255, g["visits"]))
        img.save(out, optimize=False)

    def write_base(self, out_dir: Path):
        items = self.rows(0, self.baked)
        out_dir.mkdir(parents=True, exist_ok=True)
        self.write_tsv(out_dir / "ghosts_base.tsv", items, 0)
        self.write_png(out_dir / "poses_base.png", items, 0)

    def write_new(self, out_dir: Path):
        items = self.rows(self.baked)
        out_dir.mkdir(parents=True, exist_ok=True)
        self.write_tsv(out_dir / "ghosts.tsv", items, self.baked)
        self.write_png(out_dir / "poses.png", items, self.baked)

# ----------------------------------------------------------------------------- log tailing

def default_log_dir():
    la = os.environ.get("LOCALAPPDATA")
    if la:
        return Path(la).parent / "LocalLow" / "VRChat" / "VRChat"
    return Path.home() / ".steam/steam/steamapps/compatdata/438100/pfx/drive_c/users/steamuser/AppData/LocalLow/VRChat/VRChat"

def newest_log(log_dir: Path):
    logs = sorted(glob.glob(str(log_dir / "output_log_*.txt")), key=os.path.getmtime)
    return Path(logs[-1]) if logs else None

def tail(log_dir: Path):
    """Yields new lines; follows log rotation when VRChat restarts."""
    cur, fh = None, None
    while True:
        latest = newest_log(log_dir)
        if latest and latest != cur:
            if fh:
                fh.close()
            cur = latest
            fh = open(cur, "r", encoding="utf-8", errors="replace")
            fh.seek(0, os.SEEK_END)  # only new events; rerun with --replay to backfill
            print(f"[scribe] following {cur.name}")
        if fh:
            line = fh.readline()
            if line:
                yield line
                continue
        time.sleep(0.5)

# ----------------------------------------------------------------------------- git

def git(repo: Path, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)

def publish(repo: Path, archive: Archive):
    """Replace the data repo's branch with one fresh commit holding only the new ghosts."""
    archive.write_new(repo)
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "main"
    git(repo, "checkout", "-q", "--orphan", "__ghost_publish")
    git(repo, "add", "-A")
    msg = f"ghosts: {len(archive.ghosts) - archive.baked} new @ {datetime.now(timezone.utc).isoformat(timespec='seconds')}"
    r = git(repo, "commit", "-q", "-m", msg)
    if r.returncode != 0:
        git(repo, "checkout", "-q", branch)
        git(repo, "branch", "-q", "-D", "__ghost_publish")
        print(f"[scribe] commit failed: {r.stderr.strip() or r.stdout.strip()}")
        return
    git(repo, "branch", "-q", "-D", branch)
    git(repo, "branch", "-q", "-m", branch)
    p = git(repo, "push", "-q", "-f", "origin", branch)
    print("[scribe] pushed" if p.returncode == 0 else f"[scribe] push failed: {p.stderr.strip()}")

# ----------------------------------------------------------------------------- main

def mock(archive: Archive, n: int):
    import random
    rest = [(0,0,0),(0,100,0),(0,250,0),(0,450,0),(0,550,0),(-50,420,0),(-170,420,0),(-430,420,0),(-680,420,0),
            (50,420,0),(170,420,0),(430,420,0),(680,420,0),(-90,-50,0),(-90,-500,0),(-90,-920,0),
            (90,-50,0),(90,-500,0),(90,-920,0)]
    now = int(time.time())
    for i in range(n):
        jitter = lambda v: [c + random.randint(-120, 120) for c in v]
        archive.apply({"name": f"mock_{i:03d}",
                       "ts": now - (n - i) * 3 * 86400,  # oldest first, so new rows are the recent ones
                       "height": random.randint(1200, 2100),
                       "root": [random.randint(-6000, 6000), 950, random.randint(-6000, 6000)],
                       "bones": [jitter(b) for b in rest]})

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", help="local clone of the GitHub Pages data repo (new ghosts only)")
    ap.add_argument("--log-dir", default=str(default_log_dir()))
    ap.add_argument("--archive", default=str(DEFAULT_ARCHIVE), help="local archive json (never commit this)")
    ap.add_argument("--push-every", type=int, default=60, help="seconds between publishes")
    ap.add_argument("--replay", action="store_true", help="parse all existing logs once, then follow")
    ap.add_argument("--bake", metavar="DIR", help="mark every ghost as baked, write poses_base.png + ghosts_base.tsv to DIR, exit")
    ap.add_argument("--mock", type=int, default=0, help="write N fake ghosts (80%% base, 20%% new) to --out and exit")
    ap.add_argument("--out", default="./mock", help="output dir for --mock")
    ap.add_argument("--check", metavar="LINE", help="parse one log line, print the result, exit")
    a = ap.parse_args()

    if a.check:
        ev = parse_line(a.check)
        print("INVALID (bad format or crc)" if ev is None else
              f"OK name={ev['name']} ts={ev['ts']} height={ev['height']}mm root={ev['root']} bones={len(ev['bones'])}")
        sys.exit(0 if ev else 1)

    if a.mock:
        archive = Archive(Path("/nonexistent"))  # in-memory, never saved
        mock(archive, a.mock)
        archive.baked = a.mock - a.mock // 5
        out = Path(a.out)
        archive.write_base(out)
        archive.write_new(out)
        print(f"[scribe] wrote {archive.baked} base + {a.mock - archive.baked} new mock ghosts to {out}")
        return

    archive = Archive(Path(a.archive))
    log_dir = Path(a.log_dir)

    if a.replay:
        for f in sorted(glob.glob(str(log_dir / "output_log_*.txt")), key=os.path.getmtime):
            with open(f, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    ev = parse_line(line)
                    if ev:
                        archive.apply(ev)
        archive.save()
        print(f"[scribe] replay done: {len(archive.ghosts)} ghosts")

    if a.bake:
        archive.baked = len(archive.ghosts)
        archive.write_base(Path(a.bake))
        archive.save()
        print(f"[scribe] baked {archive.baked} ghosts to {a.bake}. Publish the world, then start the scribe; "
              f"its first publish trims the data repo to new ghosts only.")
        return

    if not a.repo:
        ap.error("--repo is required to run the scribe")
    repo = Path(a.repo)

    # Publish once on start: picks up a bake done while the scribe was stopped.
    # Never bake while the scribe is running; it would save over the bake watermark.
    archive.save()
    publish(repo, archive)
    archive.dirty = False
    last_push = time.time()
    for line in tail(log_dir):
        ev = parse_line(line)
        if ev and archive.apply(ev):
            print(f"[scribe] captured: {ev['name']}")
        if archive.dirty and time.time() - last_push >= a.push_every:
            archive.save()
            publish(repo, archive)
            archive.dirty = False
            last_push = time.time()

if __name__ == "__main__":
    main()
