"""The builder's local web server: projects, library, and Bluetooth jobs (with a fake light)."""
import json, os, sys, tempfile, threading, time, unittest, urllib.error, urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import builder, fairy


class ServerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "library" / "a").mkdir(parents=True)
        (root / "library" / "index.json").write_text(json.dumps([{"id": "a/one", "name": "one"}]))
        (root / "library" / "a" / "one.json").write_text(json.dumps({"name": "one", "frames": [[254] * 800]}))
        (root / "secret.json").write_text('{"secret": true}')
        self.patches = [mock.patch.object(builder, "PROJECTS", root / "projects"), mock.patch.object(builder, "LIBRARY", root / "library")]
        for p in self.patches: p.start()
        builder.state.update(busy=False, progress=0, total=0, message="Ready", error="")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), builder.Handler)
        threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown(); self.server.server_close()
        for p in self.patches: p.stop()
        self.tmp.cleanup()

    def get(self, path):
        try:
            with urllib.request.urlopen(self.base + path) as r: return r.status, r.read()
        except urllib.error.HTTPError as e:
            with e: return e.code, e.read()

    def post(self, path, body):
        req = urllib.request.Request(self.base + path, json.dumps(body).encode(), method="POST")
        try:
            with urllib.request.urlopen(req) as r: return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            with e: return e.code, json.loads(e.read())

    def wait_idle(self, timeout=5):
        end = time.time() + timeout
        while builder.state["busy"] and time.time() < end: time.sleep(0.01)
        self.assertFalse(builder.state["busy"])


class Pages(ServerCase):
    def test_serves_the_editor_and_state(self):
        status, body = self.get("/")
        self.assertEqual(status, 200); self.assertIn(b"Fairy Builder", body)
        self.assertEqual(json.loads(self.get("/api/state")[1])["message"], "Ready")
        self.assertEqual(self.get("/nope")[0], 404)
        self.assertEqual(self.post("/api/nope", {})[0], 404)


class Projects(ServerCase):
    def test_save_list_load_round_trip(self):
        self.assertEqual(json.loads(self.get("/api/projects")[1]), [])
        status, r = self.post("/api/save", {"name": "My Tree", "frames": [[1]]})
        self.assertEqual((status, r["ok"], r["name"]), (200, True, "My Tree"))
        self.assertEqual(json.loads(self.get("/api/projects")[1]), ["My Tree"])
        self.assertEqual(json.loads(self.get("/api/load?name=My%20Tree")[1])["frames"], [[1]])

    def test_names_are_sanitised_and_cannot_escape(self):
        _, r = self.post("/api/save", {"name": "../../evil", "frames": []})
        self.assertEqual(r["name"], "evil")
        self.assertTrue((builder.PROJECTS / "evil.json").exists())
        self.assertEqual(self.get("/api/load?name=../secret")[0], 404)          # becomes "secret", which doesn't exist there
        status, r = self.post("/api/save", {"name": "...", "frames": []})
        self.assertEqual(status, 400); self.assertIn("name", r["error"])
        self.assertEqual(self.get("/api/load?name=missing")[0], 404)


class Library(ServerCase):
    def test_index_and_items(self):
        self.assertEqual(json.loads(self.get("/api/library")[1])[0]["id"], "a/one")
        status, body = self.get("/api/library/item?id=a/one")
        self.assertEqual((status, json.loads(body)["name"]), (200, "one"))

    def test_missing_and_traversal_are_refused(self):
        self.assertEqual(self.get("/api/library/item?id=a/missing")[0], 404)
        self.assertEqual(self.get("/api/library/item?id=../secret")[0], 404)
        self.assertEqual(self.get("/api/library/item?id=/etc/passwd")[0], 404)

    def test_no_library_means_an_empty_list(self):
        (builder.LIBRARY / "index.json").unlink()
        self.assertEqual(json.loads(self.get("/api/library")[1]), [])


class BluetoothJobs(ServerCase):
    def fake_send(self, calls, gate=None, fail=None):
        async def send(frames, addr=None, progress=None):
            if gate: await __import__("asyncio").get_running_loop().run_in_executor(None, gate.wait)
            if fail: raise RuntimeError(fail)
            calls.append(frames)
            if progress: progress(len(frames), len(frames))
        return mock.patch.object(fairy, "send", send)

    def project(self, n=2):
        return {"w": 40, "h": 20, "speed": 50, "direction": 0, "frames": [[254] * 800 for _ in range(n)]}

    def test_upload_sends_power_then_the_animation(self):
        calls = []
        with self.fake_send(calls):
            status, r = self.post("/api/upload", self.project())
            self.assertEqual((status, r["ok"]), (200, True))
            self.wait_idle()
        self.assertEqual(calls[0][0], fairy.power(True))
        self.assertEqual(len(calls[0]), 1 + len(__import__("anim").frames_from_project(self.project())))
        self.assertIn("done", builder.state["message"]); self.assertEqual(builder.state["error"], "")
        self.assertEqual(builder.state["progress"], builder.state["total"])

    def test_bad_project_is_rejected_before_bluetooth(self):
        calls = []
        with self.fake_send(calls):
            status, r = self.post("/api/upload", {"w": 40, "h": 20, "frames": [[1, 2, 3]]})
        self.assertEqual(status, 400); self.assertIn("800", r["error"]); self.assertEqual(calls, [])

    def test_second_job_is_refused_while_busy(self):
        gate = threading.Event(); calls = []
        with self.fake_send(calls, gate=gate):
            self.assertTrue(self.post("/api/upload", self.project())[1]["ok"])
            time.sleep(0.1)
            self.assertTrue(json.loads(self.get("/api/state")[1])["busy"])
            _, r = self.post("/api/upload", self.project())
            self.assertFalse(r["ok"]); self.assertIn("another", r["error"])
            _, r = self.post("/api/power", {"on": False})
            self.assertFalse(r["ok"])
            gate.set(); self.wait_idle()
        self.assertEqual(len(calls), 1)

    def test_failures_are_reported_and_the_server_recovers(self):
        with self.fake_send([], fail="link lost"):
            self.post("/api/power", {"on": True}); self.wait_idle()
        self.assertEqual(builder.state["error"], "link lost"); self.assertIn("failed", builder.state["message"])
        calls = []
        with self.fake_send(calls):
            self.post("/api/power", {"on": False}); self.wait_idle()
        self.assertEqual(calls, [[fairy.power(False)]]); self.assertEqual(builder.state["error"], "")

    def test_exit_from_the_connect_step_is_reported(self):
        async def send(frames, addr=None, progress=None): raise SystemExit("could not connect to the light")
        with mock.patch.object(fairy, "send", send):
            self.post("/api/power", {"on": True}); self.wait_idle()
        self.assertEqual(builder.state["error"], "could not connect to the light")


if __name__ == "__main__":
    unittest.main()
