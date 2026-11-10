#!/usr/bin/env python3
"""Control Hello Fairy (Hysiry) BLE lights without the vendor app.

Protocol (reverse-engineered from com.hsr.hellofairy1 and a phone HCI capture):
  frame = AA TYPE LEN payload... SUM     SUM = low byte of the sum of every earlier byte
  GATT  = service 49535343-fe7d-..., write 49535343-8841-... (write w/o response), notify 49535343-1e4d-...
  02 power   [0|1]
  03 light   01 H(2) S(2) V(2)   colour; H 0-360, S/V 0-1000, big-endian
             02 SCENE V(2)        built-in scene number + brightness
"""
import argparse, asyncio, colorsys, sys
from bleak import BleakClient, BleakScanner

WRITE = "49535343-8841-43f4-a8d4-ecbe34729bb3"
NOTIFY = "49535343-1e4d-4bd9-ba61-23c647249616"

def frame(kind: int, payload: bytes = b"") -> bytes:
    body = bytes([0xAA, kind, len(payload)]) + payload
    return body + bytes([sum(body) & 0xFF])

def power(on: bool) -> bytes: return frame(0x02, bytes([1 if on else 0]))
def hsv(h: int, s: int = 1000, v: int = 1000) -> bytes:
    p = bytes([1]) + b"".join(x.to_bytes(2, "big") for x in (h % 361, min(s, 1000), min(max(v, 10), 1000)))
    return frame(0x03, p)
def rgb(r: int, g: int, b: int, v: int = 1000) -> bytes:
    h, s, _ = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    return hsv(round(h * 360), round(s * 1000), v)
def scene(n: int, v: int = 1000) -> bytes:
    return frame(0x03, bytes([2, n]) + min(max(v, 10), 1000).to_bytes(2, "big"))

# ---- pictures and animations (DIY mode) -------------------------------------------------------
# Your light reports 800 LEDs, 20 per column: a 40 x 20 grid, LED index = x * 20 + y (column-major).
GRID_W, GRID_H = 40, 20
OFF, WHITE = 254, 255          # special one-byte ("H mode") colour values

def led_index(x: int, y: int, h: int = GRID_H) -> int: return x * h + y

def hue_byte(r: int, g: int, b: int) -> int:
    """The vendor app's one-byte colour: hue/2 for saturated colours, 255 white, 254 off."""
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    if v < 0.1: return OFF
    if s < 0.1: return WHITE
    return min(round(h * 360 / 2), 179)

def pic_param(direction: int, speed: int, kind: int, bright: int = 100) -> bytes:
    """d0: playback settings. direction 0 static 1 up 2 down 3 left 4 right 5 flash 6 breath;
    kind 0 edit 1 show static 2 run animation 3 new static 4 save 6 H-mode 7 new animation."""
    return frame(0xD0, bytes([direction, bright, speed, kind]))

def pic_frame_state(num: int, state: int) -> bytes:
    """d7: frame bookkeeping. state 0 new, 1 edit, 2 save, 3 delete."""
    return frame(0xD7, bytes([num, state]))

def pic_packets(num: int, colours, rgb: bool = False, max_payload: int = 238):
    """da packets for one frame. colours: 800 hue bytes (H mode) or (r,g,b) tuples (RGB mode)."""
    size = 5 if rgb else 3
    per = (max_payload - 1) // size
    for i in range(0, len(colours), per):
        body = bytes([num])
        for led in range(i, min(i + per, len(colours))):
            c = colours[led]
            body += led.to_bytes(2, "big") + (bytes(c) if rgb else bytes([c]))
        yield frame(0xDA, body)

def animation_frames(frames, speed: int = 50, direction: int = 1, rgb: bool = False):
    """Every frame the app sends, in order. frames: list of 800-colour lists. Returns (frame, delay_s).
    direction: for one picture the scroll effect (0 static, 1 up .. 6 breath); animations use 1 like the app."""
    still = len(frames) == 1
    out = [(pic_param(direction if still else 0, speed, 6), 0.1)]
    out.append((pic_param(0, speed, 7 if len(frames) > 1 else 3), 0.1))
    if len(frames) > 1: out.append((pic_frame_state(1, 0), 0.1))
    out.append((pic_param(0, speed, 0), 0.1))
    for i, fr in enumerate(frames):
        if i:
            out += [(pic_frame_state(i, 2), 0.1), (pic_frame_state(i + 1, 0), 0.1)]
        out += [(p, 0.15 if rgb else 0.05) for p in pic_packets(i + 1, fr, rgb)]
    if len(frames) > 1: out.append((pic_frame_state(len(frames), 2), 0.1))
    run_dir = direction if still else 1
    out += [(pic_param(run_dir, speed, 4), 0.3), (pic_param(run_dir, speed, 1 if still else 2), 0.1)]
    return out

# ---- text (the light renders it itself from a built-in font) -----------------------------------
TEXT_MODES = {"static": 0, "up": 1, "down": 2, "left": 3, "right": 4, "flash": 5, "breath": 6,
              "up-loop": 7, "down-loop": 8, "left-loop": 9, "right-loop": 10, "jump": 11}
MAX_TEXT = 40

def text_frames(text: str, mode: int = 3, speed: int = 50, bright: int = 100, colours=None, bg: int = OFF, slot: int = 0):
    """The app's text sequence: d3 settings, d4 counts, then each ASCII character with its colour byte.
    colours: one hue byte for all characters, or a list with one per character. slot 1-6 also saves it."""
    text = text[:MAX_TEXT]
    if any(ord(c) > 127 for c in text): raise ValueError("only ASCII text; the light's built-in font has no other characters")
    if colours is None: colours = [0]
    if isinstance(colours, int): colours = [colours]
    cols = [colours[i % len(colours)] for i in range(len(text))]
    out = [(frame(0xD3, bytes([mode, bright, speed, bg])), 0.1),
           (frame(0xD4, bytes([21, len(text), 0])), 0.1)]
    if len(text) <= 20:
        out += [(frame(0xD4, bytes([i + 1, ord(c), cols[i]])), 0.1) for i, c in enumerate(text)]
    else:
        per = 79                      # (packet size - 1) / 3 triples per db packet, like the app
        for start in range(0, len(text), per):
            chunk = text[start:start + per]
            body = bytes([len(text)])
            for j, c in enumerate(chunk): body += bytes([min(start + j + 1, 40), ord(c), cols[start + j]])
            out.append((frame(0xDB, body), 0.1))
    if slot: out.append((frame(0xD9, bytes([slot, 2])), 0.2))
    return out

async def find(addr=None):
    if addr: return addr
    d = await BleakScanner.find_device_by_filter(lambda d, a: (d.name or "").startswith("Hello Fairy"), timeout=15)
    if not d: sys.exit("no 'Hello Fairy' light found")
    return d

async def connect(addr=None, tries=4) -> BleakClient:
    """Connect and make sure services are resolved; BlueZ sometimes returns before discovery finishes."""
    for n in range(tries):
        c = BleakClient(await find(addr))
        try:
            await c.connect()
            for _ in range(20):
                try:
                    if c.services.get_characteristic(WRITE): return c
                except Exception: pass
                await asyncio.sleep(0.25)
        except Exception as e:
            print(f"connect attempt {n + 1} failed: {e}", file=sys.stderr)
        try: await c.disconnect()
        except Exception: pass
        await asyncio.sleep(1.5)
    sys.exit("could not connect to the light")

async def send(frames, addr=None, progress=None):
    c = await connect(addr)
    try:
        for i, f in enumerate(frames):
            data, delay = f if isinstance(f, tuple) else (f, 0.15)
            await c.write_gatt_char(WRITE, data, response=False)
            if progress: progress(i + 1, len(frames))
            await asyncio.sleep(delay)
    finally:
        await c.disconnect()

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--addr")
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("on"); sp.add_parser("off")
    c = sp.add_parser("color"); c.add_argument("hex"); c.add_argument("-b", "--brightness", type=int, default=100)
    an = sp.add_parser("play", help="upload an animation project (.json from the builder) and run it"); an.add_argument("file"); 
    t = sp.add_parser("text", help="show scrolling text using the light's built-in font")
    t.add_argument("text"); t.add_argument("--mode", default="left", choices=list(TEXT_MODES)); t.add_argument("--speed", type=int, default=50)
    t.add_argument("--hue", type=int, default=0, help="one-byte hue 0-179, 255 white"); t.add_argument("--slot", type=int, default=0)
    s = sp.add_parser("scene"); s.add_argument("n", type=int); s.add_argument("-b", "--brightness", type=int, default=100)
    a = ap.parse_args()
    if a.cmd == "on": fr = [power(True)]
    elif a.cmd == "off": fr = [power(False)]
    elif a.cmd == "color":
        h = a.hex.lstrip("#"); fr = [power(True), rgb(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a.brightness * 10)]
    elif a.cmd == "text":
        fr = [power(True)] + text_frames(a.text, TEXT_MODES[a.mode], a.speed, 100, a.hue, slot=a.slot)
    elif a.cmd == "play":
        import anim; fr = [power(True)] + anim.project_frames(a.file)
    else: fr = [power(True), scene(a.n, a.brightness * 10)]
    asyncio.run(send(fr, a.addr))

if __name__ == "__main__":
    main()
