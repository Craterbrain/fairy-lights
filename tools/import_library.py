#!/usr/bin/env python3
"""Turns the preset pictures and animations inside the Hello Fairy APK into builder projects.

  python3 tools/import_library.py /path/to/base.apk        # writes library/<category>/<name>.json + library/index.json

The APK is the Hello Fairy app, Android package com.hsr.hellofairy1 (by Hysiry Technology). Pull it from your own phone:
  adb shell pm path com.hsr.hellofairy1      # it is a split APK; pull the one called base.apk
  adb pull <that path> .
The artwork inside is the vendor's: use it for yourself, don't republish the APK or the generated library/.

Sources (all read straight from the APK's assets):
  picture_807807/*, picture_843843/*, ...   pixel-art JSON: form{widthPixel,heightPixel} + dotList of [r,g,b,a]
  editable_page_pixel_art/<product>/*       same format, other products' grids
  diy_preinstall/<product>/**/data.txt      the app's own upload format: ARGB ints in LED order, + speed/direction
  gif_Loca/gif_WxH/N.gif                    previews of the built-in effects on wide matrix products (needs Pillow)
Every picture becomes a 40 x 20 project of one-byte colours. Smaller grids are centred, larger ones cropped
around the centre (the project keeps "source_grid" and "cropped" so you can see what happened).
"""
import base64, io, json, re, sys, zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fairy

W, H, OFF = fairy.GRID_W, fairy.GRID_H, fairy.OFF
OUT = Path(__file__).resolve().parent.parent / "library"
# product id -> (columns, rows), taken from the app's own canvas setup, for the diy_preinstall data
PRODUCT_GRIDS = {"158158": (32, 14), "394394": (60, 6), "398398": (100, 6), "29029": (30, 30),
                 "38038": (15, 10), "843843": (20, 20), "14014": (34, 10), "387387": (30, 10), "399399": (40, 15)}

def hue(r, g, b): return fairy.hue_byte(int(r), int(g), int(b))

def place(src_w, src_h, get):
    """Centre (or centre-crop) a src_w x src_h picture onto the 40 x 20 grid. get(x, y) -> hue byte."""
    ox, oy = (W - src_w) // 2, (H - src_h) // 2
    out = [OFF] * (W * H)
    for x in range(W):
        for y in range(H):
            sx, sy = x - ox, y - oy
            if 0 <= sx < src_w and 0 <= sy < src_h: out[x * H + y] = get(sx, sy)
    return out, (src_w > W or src_h > H)

def slug(s): return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_") or "item"

def ImSequence_frames(im, ImageSequence):
    """Each GIF frame composited over black, as RGB."""
    from PIL import Image
    for fr in ImageSequence.Iterator(im):
        rgba = fr.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (0, 0, 0, 255)); bg.alpha_composite(rgba)
        yield bg.convert("RGB")

def product_of(parts):
    """('picture_807807', ...) / ('editable_page_pixel_art', '158158', ...) / ('diy_preinstall', '29029', ...) -> (product, rest)"""
    if parts[1].startswith("picture_"): return parts[1][8:], parts[2:]
    return parts[2], parts[3:]

def main(apk):
    z = zipfile.ZipFile(apk)
    OUT.mkdir(exist_ok=True)
    index, seen = [], set()
    skipped = {}
    def skip(why): skipped[why] = skipped.get(why, 0) + 1
    def add(product, cat, name, frames, src_grid, cropped, speed, direction, source):
        rel = "/".join(x for x in (product, slug(cat), slug(name)) if x)
        while rel in seen: rel += "_2"
        seen.add(rel)
        f = OUT / (rel + ".json"); f.parent.mkdir(parents=True, exist_ok=True)
        proj = {"name": slug(name), "w": W, "h": H, "speed": speed, "direction": direction, "flipX": False, "flipY": False,
                "source": source, "source_grid": list(src_grid), "cropped": cropped, "frames": frames}
        f.write_text(json.dumps(proj, separators=(",", ":")))
        index.append({"id": rel, "name": name, "product": product, "category": cat, "frames": len(frames),
                      "source_grid": list(src_grid), "native": tuple(src_grid) == (W, H), "cropped": cropped,
                      "source": source, "thumb": base64.b64encode(bytes(frames[0])).decode()})

    for n in sorted(z.namelist()):
        if not n.startswith("assets/") or not n.endswith((".json", ".txt")): continue
        parts = n.split("/")
        try: d = json.loads(z.read(n))
        except Exception: continue
        if not isinstance(d, dict): continue
        src = n.split("assets/")[1]
        if d.get("dotList") and n.endswith(".json") and parts[1] != "svg_animation":      # pixel-art editor files
            product, rest = product_of(parts)
            f = d.get("form", {}); sw, sh = f.get("widthPixel"), f.get("heightPixel")
            dl = d["dotList"]
            if not sw or not sh: skip("no grid size"); continue
            if len(dl) == sh and len(dl[0]) == sw: frames_src = [[px for row in dl for px in row]]   # one 2-D picture, row by row
            elif len(dl[0]) == sw * sh: frames_src = dl                                              # one flat list per frame
            else: skip("odd shape"); continue
            frames, crop = [], False
            for fr in frames_src:
                img, crop = place(sw, sh, lambda x, y, fr=fr: hue(*fr[y * sw + x][:3]))
                frames.append(img)
            add(product, rest[0] if len(rest) > 1 else "", Path(n).stem, frames, (sw, sh), crop, 50, 0, src)
        elif d.get("dataList") and n.endswith(".txt"):                                       # the app's upload format
            product, rest = product_of(parts)
            grid = PRODUCT_GRIDS.get(product)
            dl = d["dataList"]
            if not grid or len(dl[0]) != grid[0] * grid[1]: skip(f"preinstall with unknown grid ({product})"); continue
            sw, sh = grid; frames, crop = [], False
            for fr in dl:
                def colour(x, y, fr=fr):
                    c = fr[x * sh + y] & 0xFFFFFF
                    return hue(c >> 16 & 255, c >> 8 & 255, c & 255)
                img, crop = place(sw, sh, colour); frames.append(img)
            add(product, "preinstall", "-".join(rest[:-1]), frames, grid, crop, int(d.get("speed") or 50), int(d.get("direction") or 0), src)
    gifs = [n for n in sorted(z.namelist()) if re.match(r"assets/gif_Loca/gif_\d+x\d+/\d+\.gif$", n)]
    if gifs:
        try: from PIL import Image, ImageSequence
        except ImportError: print("Pillow is not installed, so the GIFs were skipped (pip install pillow)"); gifs = []
    for n in gifs:
        parts = n.split("/"); size = parts[2][4:]
        im = Image.open(io.BytesIO(z.read(n))); sw, sh = im.size
        frames, crop = [], False
        for fr in ImSequence_frames(im, ImageSequence):
            px = fr.load()
            img, crop = place(sw, sh, lambda x, y, px=px: hue(*px[x, y]))
            frames.append(img)
        add(f"gif{size}", "gif " + size.replace("x", "×"), Path(n).stem, frames, (sw, sh), crop, 50, 0, n.split("assets/")[1])
    index.sort(key=lambda e: (not e["native"], e["product"], e["category"], e["name"]))
    (OUT / "index.json").write_text(json.dumps(index, separators=(",", ":")))
    print(f"{len(index)} items imported to {OUT}")
    print("native 40x20:", sum(e["native"] for e in index), " cropped:", sum(e["cropped"] for e in index))
    print("skipped:", skipped or "none")

if __name__ == "__main__":
    main(sys.argv[1])
