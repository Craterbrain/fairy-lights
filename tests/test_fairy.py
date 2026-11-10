"""Protocol, animation sequencing, projects, the sender and the command line (no Bluetooth needed)."""
import asyncio, json, os, sys, tempfile, types, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import anim, fairy


def checksum_ok(f: bytes) -> bool:
    return f[0] == 0xAA and f[2] == len(f) - 4 and f[-1] == sum(f[:-1]) & 0xFF


class Frames(unittest.TestCase):
    def test_frames_match_the_phone_app_capture(self):
        # bytes seen in the HCI capture of the vendor app
        self.assertEqual(fairy.frame(0x00).hex(), "aa0000aa")
        self.assertEqual(fairy.frame(0x0C).hex(), "aa0c00b6")
        self.assertEqual(fairy.frame(0x05, bytes.fromhex("6af299d6000168")).hex(), "aa05076af299d6000168ea")
        self.assertEqual(fairy.frame(0xD0, bytes([0, 0x64, 0x54, 6])).hex(), "aad004006454063c")

    def test_power(self):
        self.assertEqual(fairy.power(True).hex(), "aa020101ae")
        self.assertEqual(fairy.power(False).hex(), "aa020100ad")

    def test_colour_and_scene(self):
        self.assertEqual(fairy.hsv(0).hex(), "aa030701000003e803e88b")
        self.assertEqual(fairy.hsv(361, 5000, 5).hex(), fairy.hsv(0, 1000, 10).hex())   # wraps hue, clamps S and V
        self.assertEqual(fairy.rgb(255, 0, 0, 500)[8:10], (500).to_bytes(2, "big"))    # brightness lands in V
        self.assertEqual(fairy.rgb(0, 255, 0)[4:6], (120).to_bytes(2, "big"))
        s = fairy.scene(4, 5)
        self.assertEqual(s[3:7], bytes([2, 4, 0, 10]))
        self.assertTrue(all(checksum_ok(x) for x in (fairy.hsv(10), fairy.rgb(1, 2, 3), s)))


class Colours(unittest.TestCase):
    def test_hue_byte(self):
        self.assertEqual([fairy.hue_byte(255, 0, 0), fairy.hue_byte(0, 255, 0), fairy.hue_byte(0, 0, 255)], [0, 60, 120])
        self.assertEqual(fairy.hue_byte(255, 255, 255), fairy.WHITE)
        self.assertEqual(fairy.hue_byte(128, 128, 128), fairy.WHITE)     # grey counts as white
        self.assertEqual(fairy.hue_byte(0, 0, 0), fairy.OFF)
        self.assertEqual(fairy.hue_byte(20, 10, 10), fairy.OFF)          # too dark to see
        self.assertLessEqual(fairy.hue_byte(255, 0, 5), 179)             # never reaches the special values

    def test_led_index_is_column_major(self):
        self.assertEqual(fairy.led_index(0, 0), 0)
        self.assertEqual(fairy.led_index(1, 0), 20)
        self.assertEqual(fairy.led_index(39, 19), 799)


class Pictures(unittest.TestCase):
    def test_packets_cover_every_led_once(self):
        pk = list(fairy.pic_packets(3, list(range(100)) * 8))
        self.assertEqual(len(pk), 11)
        self.assertTrue(all(checksum_ok(p) and p[1] == 0xDA and p[3] == 3 for p in pk))
        self.assertEqual([len(p) for p in pk[:-1]], [242] * 10)
        seen = []
        for p in pk:
            body = p[4:-1]
            seen += [int.from_bytes(body[i:i + 2], "big") for i in range(0, len(body), 3)]
        self.assertEqual(seen, list(range(800)))

    def test_first_packet_matches_the_capture(self):
        first = next(fairy.pic_packets(1, [fairy.OFF] * 800))
        self.assertTrue(first.hex().startswith("aadaee01" "0000fe" "0001fe" "0002fe"))
        self.assertEqual(first[-1], 0xDE)

    def test_rgb_packets_are_five_bytes_per_led(self):
        first = next(fairy.pic_packets(1, [(1, 2, 3)] * 800, rgb=True))
        self.assertEqual(first[4:9], bytes([0, 0, 1, 2, 3]))
        self.assertEqual((len(first) - 5) // 5, 47)

    def kinds(self, steps):
        return [(s[0][1], s[0][3:]) for s in steps]

    def test_single_picture_sequence(self):
        steps = fairy.animation_frames([[fairy.OFF] * 800], speed=33, direction=5)
        self.assertEqual(steps[0][0], fairy.pic_param(5, 33, 6))
        self.assertEqual(steps[1][0], fairy.pic_param(0, 33, 3))
        self.assertEqual(steps[-2][0], fairy.pic_param(5, 33, 4))         # save keeps the scroll effect
        self.assertEqual(steps[-1][0], fairy.pic_param(5, 33, 1))         # show static
        self.assertEqual(len(steps), 3 + 11 + 2)                           # 3 setup, 11 packets, save + show
        self.assertFalse(any(s[0][1] == 0xD7 for s in steps))

    def test_animation_sequence(self):
        steps = fairy.animation_frames([[fairy.OFF] * 800] * 3, speed=50, direction=5)
        d = [s[0] for s in steps]
        self.assertEqual(d[:4], [fairy.pic_param(0, 50, 6), fairy.pic_param(0, 50, 7), fairy.pic_frame_state(1, 0), fairy.pic_param(0, 50, 0)])
        self.assertEqual(d[-2:], [fairy.pic_param(1, 50, 4), fairy.pic_param(1, 50, 2)])   # animations ignore the effect
        states = [(x[3], x[4]) for x in d if x[1] == 0xD7]
        self.assertEqual(states, [(1, 0), (1, 2), (2, 0), (2, 2), (3, 0), (3, 2)])
        frames_sent = [x[3] for x in d if x[1] == 0xDA]
        self.assertEqual(frames_sent, [1] * 11 + [2] * 11 + [3] * 11)
        self.assertTrue(all(checksum_ok(x) for x in d))
        self.assertTrue(all(delay in (0.05, 0.1, 0.3) for _, delay in steps))


class Text(unittest.TestCase):
    def test_short_text(self):
        f = [x for x, _ in fairy.text_frames("HI", 3, 50, 100, [0, 60])]
        self.assertEqual(f[0].hex(), "aad304036432fe18")
        self.assertEqual(f[1].hex(), "aad4031502" "00" "98")
        self.assertEqual([x[3:6] for x in f[2:]], [bytes([1, ord("H"), 0]), bytes([2, ord("I"), 60])])

    def test_long_text_uses_the_bulk_command(self):
        f = [x for x, _ in fairy.text_frames("A" * 30)]
        bulk = [x for x in f if x[1] == 0xDB]
        self.assertEqual(len(bulk), 1)
        self.assertEqual(bulk[0][3], 30)
        self.assertEqual(bulk[0][4:7], bytes([1, ord("A"), 0]))

    def test_limits_and_slot(self):
        self.assertEqual(fairy.text_frames("x" * 60)[1][0][4], 40)          # capped at 40 characters
        with self.assertRaises(ValueError): fairy.text_frames("héllo")
        self.assertEqual(fairy.text_frames("a", slot=2)[-1][0], fairy.frame(0xD9, bytes([2, 2])))
        self.assertEqual(fairy.text_frames("ab", colours=7)[3][0][5], 7)


class Projects(unittest.TestCase):
    def project(self, n=1, **kw):
        return {"w": 40, "h": 20, "speed": 50, "direction": 0, "frames": [[fairy.OFF] * 800 for _ in range(n)], **kw}

    def test_flips_mirror_the_picture(self):
        fr = [fairy.OFF] * 800; fr[0] = 10                  # top-left in display order
        self.assertEqual(anim.to_led_order(fr, 40, 20)[0], 10)
        self.assertEqual(anim.to_led_order(fr, 40, 20, flip_x=True)[fairy.led_index(39, 0)], 10)
        self.assertEqual(anim.to_led_order(fr, 40, 20, flip_y=True)[fairy.led_index(0, 19)], 10)
        self.assertEqual(anim.to_led_order(fr, 40, 20, True, True)[799], 10)

    def test_colour_strings_and_blanks(self):
        self.assertEqual(anim._one(5), 5)
        self.assertEqual(anim._one(""), fairy.OFF)
        self.assertEqual(anim._one(None), fairy.OFF)
        self.assertEqual(anim._one("#00ff00"), 60)

    def test_validation(self):
        with self.assertRaises(ValueError): anim.frames_from_project(self.project(0))
        with self.assertRaises(ValueError): anim.frames_from_project(self.project(256))
        with self.assertRaises(ValueError): anim.frames_from_project({"w": 40, "h": 20, "frames": [[1, 2, 3]]})
        self.assertEqual(len(anim.frames_from_project(self.project(255))[0][0]), 8)    # 255 frames is fine

    def test_loading_a_file_and_defaults(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"frames": [[fairy.OFF] * 800]}, f)
        try:
            steps = anim.project_frames(f.name)
            self.assertEqual(steps[0][0], fairy.pic_param(0, 50, 6))               # speed 50, direction 0 by default
        finally:
            os.unlink(f.name)


class Sender(unittest.TestCase):
    def run_send(self, frames, fail_at=None, progress=None):
        class Client:
            def __init__(self): self.writes, self.closed = [], False
            async def write_gatt_char(self, char, data, response):
                if fail_at is not None and len(self.writes) == fail_at: raise OSError("link lost")
                self.writes.append((char, data, response))
            async def disconnect(self): self.closed = True
        client = Client(); slept = []
        async def fake_connect(addr=None): return client
        async def fake_sleep(d): slept.append(d)
        with mock.patch.object(fairy, "connect", fake_connect), mock.patch.object(fairy.asyncio, "sleep", fake_sleep):
            try: asyncio.run(fairy.send(frames, progress=progress)); err = None
            except OSError as e: err = e
        return client, slept, err

    def test_writes_in_order_with_delays_and_progress(self):
        seen = []
        client, slept, err = self.run_send([b"a", (b"b", 0.5)], progress=lambda i, n: seen.append((i, n)))
        self.assertIsNone(err)
        self.assertEqual([w[1] for w in client.writes], [b"a", b"b"])
        self.assertTrue(all(w[0] == fairy.WRITE and w[2] is False for w in client.writes))
        self.assertEqual(slept, [0.15, 0.5])
        self.assertEqual(seen, [(1, 2), (2, 2)])
        self.assertTrue(client.closed)

    def test_disconnects_even_when_a_write_fails(self):
        client, _, err = self.run_send([b"a", b"b"], fail_at=1)
        self.assertIsInstance(err, OSError)
        self.assertTrue(client.closed)


class CommandLine(unittest.TestCase):
    def run_cli(self, *argv):
        captured = {}
        async def fake_send(frames, addr=None): captured["frames"], captured["addr"] = frames, addr
        with mock.patch.object(fairy, "send", fake_send), mock.patch.object(sys, "argv", ["fairy.py", *argv]):
            fairy.main()
        return captured

    def test_on_off(self):
        self.assertEqual(self.run_cli("on")["frames"], [fairy.power(True)])
        self.assertEqual(self.run_cli("--addr", "AA:BB", "off"), {"frames": [fairy.power(False)], "addr": "AA:BB"})

    def test_colour(self):
        fr = self.run_cli("color", "#ff0000", "-b", "50")["frames"]
        self.assertEqual(fr, [fairy.power(True), fairy.rgb(255, 0, 0, 500)])

    def test_scene_text_and_play(self):
        self.assertEqual(self.run_cli("scene", "3")["frames"], [fairy.power(True), fairy.scene(3, 1000)])
        t = self.run_cli("text", "HI", "--mode", "right", "--hue", "60")["frames"]
        self.assertEqual(t[0], fairy.power(True)); self.assertEqual(t[1][0][3], 4)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump({"frames": [[fairy.OFF] * 800] * 2}, f)
        try:
            p = self.run_cli("play", f.name)["frames"]
            self.assertEqual(p[0], fairy.power(True)); self.assertEqual(p[-1][0][5:7], bytes([50, 2]))
        finally:
            os.unlink(f.name)


class Connecting(unittest.TestCase):
    """fairy.connect/find against fake Bluetooth objects: BlueZ often returns before services are resolved."""
    def fake_client(self, behaviours):
        made = []
        class Services:
            def __init__(self, ready): self.ready = ready
            def get_characteristic(self, uuid):
                if self.ready is None: raise RuntimeError("Service Discovery has not been performed yet")
                return object() if self.ready else None
        class Client:
            def __init__(self, device):
                self.device = device; self.mode = behaviours[len(made)]; self.disconnects = 0; made.append(self)
                self.services = Services({"ok": True, "unresolved": None, "nochar": False}.get(self.mode))
            async def connect(self):
                if self.mode == "refuse": raise OSError("refused")
            async def disconnect(self): self.disconnects += 1
        return Client, made

    def connect(self, behaviours, **kw):
        Client, made = self.fake_client(behaviours)
        async def fake_find(addr=None): return addr or "light"
        async def fake_sleep(d): pass
        with mock.patch.object(fairy, "BleakClient", Client), mock.patch.object(fairy, "find", fake_find), \
             mock.patch.object(fairy.asyncio, "sleep", fake_sleep), mock.patch("sys.stderr"):
            try: return asyncio.run(fairy.connect(**kw)), made
            except SystemExit as e: return e, made

    def test_connects_first_time(self):
        c, made = self.connect(["ok"])
        self.assertIs(c, made[0]); self.assertEqual(len(made), 1)

    def test_retries_after_a_refused_connection_and_unresolved_services(self):
        c, made = self.connect(["refuse", "unresolved", "nochar", "ok"])
        self.assertIs(c, made[3]); self.assertEqual([m.disconnects for m in made], [1, 1, 1, 0])

    def test_gives_up_after_the_last_try(self):
        e, made = self.connect(["refuse"] * 4)
        self.assertIsInstance(e, SystemExit); self.assertEqual(len(made), 4)
        e, made = self.connect(["refuse"] * 2, tries=2)
        self.assertIsInstance(e, SystemExit); self.assertEqual(len(made), 2)

    def test_find_uses_the_address_it_is_given_or_scans_for_the_name(self):
        self.assertEqual(asyncio.run(fairy.find("AA:BB")), "AA:BB")
        seen = {}
        async def scan(pred, timeout):
            dev = lambda name: types.SimpleNamespace(name=name)
            seen["named"] = pred(dev("Hello Fairy-1234"), None)
            seen["other"] = pred(dev("Other"), None); seen["none"] = pred(dev(None), None)
            return "device"
        with mock.patch.object(fairy.BleakScanner, "find_device_by_filter", scan):
            self.assertEqual(asyncio.run(fairy.find()), "device")
        self.assertEqual(seen, {"named": True, "other": False, "none": False})
        async def nothing(pred, timeout): return None
        with mock.patch.object(fairy.BleakScanner, "find_device_by_filter", nothing):
            with self.assertRaises(SystemExit): asyncio.run(fairy.find())


if __name__ == "__main__":
    unittest.main()
