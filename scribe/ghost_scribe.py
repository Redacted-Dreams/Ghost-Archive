#!/usr/bin/env python3
"""
Ghost Archive scribe.

Tails the newest VRChat output log on this machine, parses [GHOST1] / [GHOSTX] lines,
maintains archive/ghosts.json (source of truth), and periodically writes
  <repo>/ghosts.tsv   and   <repo>/poses.png
then commits + pushes so GitHub Pages serves them.

Usage:
  python ghost_scribe.py --repo /path/to/pages-repo [--log-dir ...] [--push-every 60]

Requires: pillow. git must be configured with push credentials for the repo.
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

LINE_RE = re.compile(r"\[(GHOST1|GHOSTX)\]\|(.*)$")

# ----------------------------------------------------------------------------- parsing

def crc(s: str) -> int:
    return sum(ord(c) for c in s) & 0xFFFF

def parse_line(line: str):
    m = LINE_RE.search(line)
    if not m:
        return None
    tag, rest = m.group(1), m.group(2).rstrip("\r\n")
    body, sep, crc_s = rest.rpartition("|")
    if not sep or not crc_s.isdigit() or crc(body) != int(crc_s):
        return None
    f = body.split("|")
    try:
        if tag == "GHOSTX":
            name, ts = f[0], int(f[1])
            return {"kind": "tombstone", "name": name, "ts": ts}
        name, ts, height = f[0], int(f[1]), int(f[2])
        root = [int(v) for v in f[3].split(",")]
        bones = [[int(v) for v in b.split(",")] for b in f[4].split(";")]
        if len(root) != 3 or len(bones) != BONES:
            return None
        if not (300 <= height <= 6000):
            return None
        return {"kind": "capture", "name": name, "ts": ts, "height": height,
                "root": root, "bones": bones}
    except (ValueError, IndexError):
        return None

def day_of(ts: int) -> int:
    return int((datetime.fromtimestamp(ts, timezone.utc) - EPOCH_2020).days)

# ----------------------------------------------------------------------------- archive

class Archive:
    def __init__(self, path: Path):
        self.path = path
        self.ghosts = {}          # name -> record
        self.tombstones = set()   # names that opted out
        self.blocklist = set()    # moderation
        self.dirty = False
        self.seen = set()         # (name, ts) dedup for multi-bot logs
        if path.exists():
            d = json.loads(path.read_text(encoding="utf-8"))
            self.ghosts = d.get("ghosts", {})
            self.tombstones = set(d.get("tombstones", []))
            self.blocklist = set(d.get("blocklist", []))

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "v": 1,
            "ghosts": self.ghosts,
            "tombstones": sorted(self.tombstones),
            "blocklist": sorted(self.blocklist),
        }, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def apply(self, ev):
        key = (ev["name"], ev["ts"])
        if key in self.seen:
            return
        self.seen.add(key)
        name = ev["name"]
        if ev["kind"] == "tombstone":
            self.tombstones.add(name)
            if name in self.ghosts:
                del self.ghosts[name]
            self.dirty = True
            return
        if name in self.tombstones or name in self.blocklist:
            return
        day = day_of(ev["ts"])
        if name in self.ghosts:
            g = self.ghosts[name]
            if day > g["lastSeenDay"]:
                g["visits"] += 1
                g["lastSeenDay"] = day
                self.dirty = True
            return  # first pose wins
        self.ghosts[name] = {
            "captureDay": day, "lastSeenDay": day, "visits": 1,
            "height": ev["height"], "root": ev["root"], "bones": ev["bones"],
            "ts": ev["ts"],
        }
        self.dirty = True

    # ---- export

    def ordered(self):
        # oldest first, so row index is stable as new ghosts append
        return sorted(self.ghosts.items(), key=lambda kv: (kv[1]["ts"], kv[0]))

    def write_tsv(self, out: Path):
        rows = ["v\t1", "name\tcaptureDay\tlastSeenDay\tvisits\trow"]
        for i, (name, g) in enumerate(self.ordered()):
            rows.append(f"{name}\t{g['captureDay']}\t{g['lastSeenDay']}\t{g['visits']}\t{i}")
        out.write_text("\n".join(rows) + "\n", encoding="utf-8")

    def write_png(self, out: Path):
        items = self.ordered()
        h = 64
        while h < len(items):
            h *= 2
        img = Image.new("RGBA", (PNG_W, h), (0, 0, 0, 0))
        px = img.load()

        def u16(v):  # clamp to 16 bit
            return max(0, min(65535, int(v)))

        def put(x, y, a, b):
            a, b = u16(a), u16(b)
            px[x, y] = (a & 0xFF, a >> 8, b & 0xFF, b >> 8)

        for y, (name, g) in enumerate(items):
            rx, ry, rz = g["root"]
            put(0, y, rx // 8 + 32768, ry // 8 + 32768)
            put(1, y, rz // 8 + 32768, g["height"])
            for i, (bx, by, bz) in enumerate(g["bones"]):
                put(2 + 2 * i, y, bx + 32768, by + 32768)
                put(3 + 2 * i, y, bz + 32768, 0)
            put(40, y, g["captureDay"], min(255, g["visits"]) | (0 << 8))
        img.save(out, optimize=False)

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
    archive.write_tsv(repo / "ghosts.tsv")
    archive.write_png(repo / "poses.png")
    git(repo, "add", "ghosts.tsv", "poses.png")
    msg = f"ghosts: {len(archive.ghosts)} @ {datetime.now(timezone.utc).isoformat(timespec='seconds')}"
    r = git(repo, "commit", "-m", msg)
    if r.returncode == 0:
        p = git(repo, "push")
        print("[scribe] pushed" if p.returncode == 0 else f"[scribe] push failed: {p.stderr.strip()}")

# ----------------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True, help="local clone of the GitHub Pages repo")
    ap.add_argument("--log-dir", default=str(default_log_dir()))
    ap.add_argument("--archive", default=None, help="ghosts.json path (default: <repo>/archive/ghosts.json)")
    ap.add_argument("--push-every", type=int, default=60, help="seconds between publishes")
    ap.add_argument("--replay", action="store_true", help="parse all existing logs once, then follow")
    ap.add_argument("--mock", type=int, default=0, help="write N fake ghosts to the repo files and exit (no git)")
    a = ap.parse_args()

    repo = Path(a.repo)
    archive = Archive(Path(a.archive) if a.archive else repo / "archive" / "ghosts.json")
    log_dir = Path(a.log_dir)

    if a.mock:
        import random
        rest = [(0,0,0),(0,100,0),(0,250,0),(0,450,0),(0,550,0),(-50,420,0),(-170,420,0),(-430,420,0),(-680,420,0),
                (50,420,0),(170,420,0),(430,420,0),(680,420,0),(-90,-50,0),(-90,-500,0),(-90,-920,0),
                (90,-50,0),(90,-500,0),(90,-920,0)]
        now = int(time.time())
        for i in range(a.mock):
            jitter = lambda v: [c + random.randint(-120, 120) for c in v]
            archive.apply({"kind": "capture", "name": f"mock_{i:03d}",
                           "ts": now - random.randint(0, 3 * 365 * 86400),
                           "height": random.randint(1200, 2100),
                           "root": [random.randint(-6000, 6000), 950, random.randint(-6000, 6000)],
                           "bones": [jitter(b) for b in rest]})
        archive.write_tsv(repo / "ghosts.tsv")
        archive.write_png(repo / "poses.png")
        print(f"[scribe] wrote {a.mock} mock ghosts to {repo}")
        return

    if a.replay:
        for f in sorted(glob.glob(str(log_dir / "output_log_*.txt")), key=os.path.getmtime):
            with open(f, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    ev = parse_line(line)
                    if ev:
                        archive.apply(ev)
        print(f"[scribe] replay done: {len(archive.ghosts)} ghosts")

    last_push = 0.0
    for line in tail(log_dir):
        ev = parse_line(line)
        if ev:
            archive.apply(ev)
            print(f"[scribe] {ev['kind']}: {ev['name']}")
        if archive.dirty and time.time() - last_push >= a.push_every:
            archive.save()
            publish(repo, archive)
            archive.dirty = False
            last_push = time.time()

if __name__ == "__main__":
    main()
