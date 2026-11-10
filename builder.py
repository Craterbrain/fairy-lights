#!/usr/bin/env python3
"""Animation builder for Hello Fairy lights: a local web page for painting frames, plus a Bluetooth uploader.

  .venv/bin/python builder.py            # then open http://localhost:8780
  .venv/bin/python builder.py --lan      # also reachable from a phone on the same network (no password!)
"""
import argparse, asyncio, json, re, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import anim, fairy

HERE = Path(__file__).parent
PROJECTS = HERE / "projects"
LIBRARY = HERE / "library"
lock = threading.Lock()
state = {"busy": False, "progress": 0, "total": 0, "message": "Ready", "error": ""}

def run_job(title, make_frames):
    """Runs one Bluetooth job at a time on a worker thread; the page polls /api/state."""
    if not lock.acquire(blocking=False):
        return False
    def work():
        try:
            state.update(busy=True, progress=0, total=0, error="", message=title)
            frames = make_frames()
            state["total"] = len(frames)
            def prog(i, n): state.update(progress=i, total=n)
            asyncio.run(fairy.send(frames, progress=prog))
            state["message"] = f"{title}: done"
        except BaseException as e:   # SystemExit from fairy.connect too
            state.update(error=str(e) or type(e).__name__, message=f"{title}: failed")
        finally:
            state["busy"] = False
            lock.release()
    threading.Thread(target=work, daemon=True).start()
    return True

def safe_name(name):
    name = re.sub(r"[^A-Za-z0-9 _.-]", "", name).strip().strip(".")
    if not name: raise ValueError("project needs a name")
    return name

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def reply(self, obj, code=200, ctype="application/json"):
        body = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path); q = parse_qs(u.query)
        if u.path == "/": return self.reply((HERE / "builder.html").read_bytes(), ctype="text/html; charset=utf-8")
        if u.path == "/api/state": return self.reply(state)
        if u.path == "/api/projects": return self.reply(sorted(p.stem for p in PROJECTS.glob("*.json")))
        if u.path == "/api/load":
            f = PROJECTS / (safe_name(q["name"][0]) + ".json")
            return self.reply(f.read_bytes()) if f.exists() else self.reply({"error": "not found"}, 404)
        if u.path == "/api/library":
            f = LIBRARY / "index.json"
            return self.reply(f.read_bytes()) if f.exists() else self.reply([])
        if u.path == "/api/library/item":
            f = (LIBRARY / (q["id"][0] + ".json")).resolve()
            if LIBRARY.resolve() not in f.parents or not f.exists(): return self.reply({"error": "not found"}, 404)
            return self.reply(f.read_bytes())
        self.reply({"error": "not found"}, 404)

    def do_POST(self):
        u = urlparse(self.path)
        try:
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if u.path == "/api/save":
                PROJECTS.mkdir(exist_ok=True)
                name = safe_name(data["name"]); data["name"] = name
                (PROJECTS / f"{name}.json").write_text(json.dumps(data))
                return self.reply({"ok": True, "name": name})
            if u.path == "/api/upload":
                frames = anim.frames_from_project(data)          # validates before touching Bluetooth
                ok = run_job(f"Uploading {len(data['frames'])} frame(s)", lambda: [fairy.power(True)] + frames)
                return self.reply({"ok": ok, "error": "" if ok else "another Bluetooth job is running"})
            if u.path == "/api/power":
                ok = run_job("Power " + ("on" if data["on"] else "off"), lambda: [fairy.power(bool(data["on"]))])
                return self.reply({"ok": ok})
        except Exception as e:
            return self.reply({"ok": False, "error": str(e)}, 400)
        self.reply({"error": "not found"}, 404)

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, default=8780); ap.add_argument("--lan", action="store_true")
    a = ap.parse_args()
    host = "0.0.0.0" if a.lan else "127.0.0.1"
    print(f"Fairy builder on http://{'<this-pc-ip>' if a.lan else 'localhost'}:{a.port}" + ("  (LAN: anyone on your network can use it)" if a.lan else ""))
    ThreadingHTTPServer((host, a.port), Handler).serve_forever()
