"""tools/import_library.py, run on a tiny made-up APK so the real (vendor) one isn't needed."""
import base64, importlib.util, io, json, os, sys, tempfile, unittest, zipfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("import_library", ROOT / "tools" / "import_library.py")
imp = importlib.util.module_from_spec(spec); spec.loader.exec_module(imp)
import fairy

try:
    from PIL import Image
except ImportError:
    Image = None

BLACK, RED, GREEN = [0, 0, 0, 1], [255, 0, 0, 1], [0, 255, 0, 1]


def make_apk(path):
    flat = [BLACK] * 800; flat[5 * 40 + 3] = RED                      # row-major: y = 5, x = 3
    two_d = [[BLACK] * 20 for _ in range(20)]; two_d[2][4] = GREEN     # row 2, column 4
    led_order = [0xFF000000] * 448; led_order[1 * 14 + 2] = 0xFF00FF00  # LED order x * rows + y: x = 1, y = 2
    files = {
        "assets/picture_807807/christmas/tree.json": {"form": {"widthPixel": 40, "heightPixel": 20}, "dotList": [flat, [BLACK] * 800]},
        "assets/picture_843843/science/atom.json": {"form": {"widthPixel": 20, "heightPixel": 20}, "dotList": two_d},
        "assets/diy_preinstall/158158/h/picture_1000_2/data.txt": {"direction": 5, "speed": 80, "dataList": [led_order]},
        "assets/diy_preinstall/9999/h/odd/data.txt": {"dataList": [[0xFF000000] * 10]},                 # grid unknown: skipped
        "assets/picture_807807/odd/shape.json": {"form": {"widthPixel": 40, "heightPixel": 20}, "dotList": [[1, 2]]},  # odd shape: skipped
        "assets/picture_807807/odd/nogrid.json": {"dotList": [[BLACK]]},                               # no grid size: skipped
        "assets/svg_animation/christmas/data.json": {"v": "5.12", "layers": []},                         # not a picture
    }
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items(): z.writestr(name, json.dumps(data))
        z.writestr("assets/broken.json", "{not json")
        z.writestr("assets/readme.txt", "hello")
        if Image:
            for size, x in (((32, 16), 3), ((64, 16), 30)):                # a red 2-pixel-wide bar on a black two-frame GIF
                frames = []
                for f in range(2):
                    im = Image.new("RGB", size, (0, 0, 0))
                    if f == 0:
                        for yy in range(16):
                            for xx in (x, x + 1): im.putpixel((xx, yy), (255, 0, 0))
                    frames.append(im.convert("P"))
                buf = io.BytesIO(); frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:], loop=0)
                z.writestr(f"assets/gif_Loca/gif_{size[0]}x{size[1]}/1.gif", buf.getvalue())


class Place(unittest.TestCase):
    def test_small_pictures_are_centred(self):
        img, cropped = imp.place(20, 10, lambda x, y: 7 if (x, y) == (0, 0) else fairy.OFF)
        self.assertFalse(cropped)
        self.assertEqual(img[10 * 20 + 5], 7)                  # x = 10, y = 5
        self.assertEqual(sum(v != fairy.OFF for v in img), 1)

    def test_big_pictures_are_cropped_around_the_centre(self):
        img, cropped = imp.place(60, 6, lambda x, y: 9 if x == 30 else fairy.OFF)
        self.assertTrue(cropped)
        self.assertEqual(img[20 * 20 + 7], 9)                  # source column 30 lands in the middle column
        img, _ = imp.place(100, 6, lambda x, y: 5)
        self.assertEqual(img[0 * 20 + 7], 5)

    def test_slug(self):
        self.assertEqual(imp.slug("a b/c"), "a_b_c"); self.assertEqual(imp.slug("///"), "item")


class Import(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "library"
        apk = Path(cls.tmp.name) / "fake.apk"; make_apk(apk)
        imp.OUT = cls.out
        buf = io.StringIO()
        with redirect_stdout(buf): imp.main(str(apk))
        cls.log = buf.getvalue()
        cls.index = {e["id"]: e for e in json.loads((cls.out / "index.json").read_text())}

    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()

    def project(self, id): return json.loads((self.out / f"{id}.json").read_text())

    def test_what_was_imported_and_what_was_skipped(self):
        self.assertIn("807807/christmas/tree", self.index)
        self.assertIn("843843/science/atom", self.index)
        self.assertIn("158158/preinstall/h-picture_1000_2", self.index)
        self.assertNotIn("9999", " ".join(self.index)); self.assertNotIn("807807/odd/shape", self.index)
        self.assertIn("preinstall with unknown grid (9999)", self.log); self.assertIn("odd shape", self.log); self.assertIn("no grid size", self.log)

    def test_native_pictures_keep_their_pixels_and_row_order(self):
        e, p = self.index["807807/christmas/tree"], self.project("807807/christmas/tree")
        self.assertTrue(e["native"]); self.assertFalse(e["cropped"]); self.assertEqual(e["frames"], 2)
        self.assertEqual(p["frames"][0][3 * 20 + 5], 0)                     # red at x = 3, y = 5
        self.assertEqual(sum(v != fairy.OFF for v in p["frames"][0]), 1)
        self.assertTrue(all(len(f) == 800 for f in p["frames"]))
        self.assertEqual((p["w"], p["h"]), (40, 20))

    def test_two_dimensional_pictures_are_centred(self):
        e, p = self.index["843843/science/atom"], self.project("843843/science/atom")
        self.assertFalse(e["native"]); self.assertEqual(e["source_grid"], [20, 20])
        self.assertEqual(p["frames"][0][14 * 20 + 2], 60)                   # green: column 4 + 10, row 2

    def test_preinstalled_pictures_use_led_order_and_keep_speed_and_direction(self):
        p = self.project("158158/preinstall/h-picture_1000_2")
        self.assertEqual((p["speed"], p["direction"]), (80, 5))
        self.assertEqual(p["frames"][0][5 * 20 + 5], 60)                    # x = 1 + 4, y = 2 + 3

    def test_thumbnails_are_the_first_frame(self):
        e = self.index["807807/christmas/tree"]
        self.assertEqual(list(base64.b64decode(e["thumb"])), self.project("807807/christmas/tree")["frames"][0])

    @unittest.skipUnless(Image, "Pillow not installed")
    def test_gifs(self):
        narrow, wide = self.index["gif32x16/gif_32_16/1"], self.index["gif64x16/gif_64_16/1"]
        self.assertEqual((narrow["frames"], narrow["cropped"], narrow["category"]), (2, False, "gif 32×16"))
        self.assertTrue(wide["cropped"])
        n = self.project("gif32x16/gif_32_16/1")["frames"]
        self.assertEqual(n[0][(4 + 3) * 20 + 2], 0)                           # bar column 3 + 4, row 0 + 2
        self.assertEqual(sum(v != fairy.OFF for v in n[1]), 0)               # second frame is empty
        w = self.project("gif64x16/gif_64_16/1")["frames"]
        self.assertEqual(w[0][(30 - 12) * 20 + 2], 0)                         # 64 -> 40 crops 12 columns off the left

    def test_index_is_sorted_native_first(self):
        order = [e["native"] for e in json.loads((self.out / "index.json").read_text())]
        self.assertEqual(order, sorted(order, reverse=True))


if __name__ == "__main__":
    unittest.main()
