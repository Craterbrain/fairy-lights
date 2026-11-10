"""Animation projects: JSON files made by the builder, turned into the frames the light needs.

{"w": 40, "h": 20, "speed": 50, "direction": 0, "flipX": false, "flipY": false,
 "frames": [[800 hue bytes, indexed x * 20 + y in *display* order], ...]}
A hue byte is hue/2 (0-179), 255 white, 254 off. "#rrggbb" strings are also accepted.
flipX / flipY mirror the picture at send time, in case the light's wiring runs the other way.
"""
import json
import fairy

MAX_FRAMES = 255   # the frame number is one byte in the protocol; the app itself stops at 5

def _one(c):
    if isinstance(c, int): return c
    if not c: return fairy.OFF
    c = c.lstrip("#")
    return fairy.hue_byte(int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))

def to_led_order(frame, w, h, flip_x=False, flip_y=False):
    out = [fairy.OFF] * (w * h)
    for x in range(w):
        for y in range(h):
            out[fairy.led_index(w - 1 - x if flip_x else x, h - 1 - y if flip_y else y, h)] = _one(frame[x * h + y])
    return out

def project_frames(path):
    return frames_from_project(json.load(open(path)))

def frames_from_project(p):
    w, h = p.get("w", fairy.GRID_W), p.get("h", fairy.GRID_H)
    if not 1 <= len(p["frames"]) <= MAX_FRAMES:
        raise ValueError(f"need 1 to {MAX_FRAMES} frames, got {len(p['frames'])}")
    frames = []
    for fr in p["frames"]:
        if len(fr) != w * h: raise ValueError(f"frame has {len(fr)} pixels, expected {w * h}")
        frames.append(to_led_order(fr, w, h, p.get("flipX", False), p.get("flipY", False)))
    return fairy.animation_frames(frames, int(p.get("speed", 50)), int(p.get("direction", 0)))
