#!/usr/bin/env python3
"""Desktop window for Hello Fairy lights. Run: .venv/bin/python fairy_gui.py"""
import asyncio, colorsys, threading, tkinter as tk
from tkinter import ttk
from bleak import BleakClient
import fairy

class Link:
    """Keeps one BLE connection open on a background asyncio loop."""
    def __init__(self, status):
        self.status, self.client = status, None
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

    def connect(self):
        asyncio.run_coroutine_threadsafe(self._connect(), self.loop)

    async def _connect(self):
        if self.client and self.client.is_connected: return
        self.status("Scanning for a Hello Fairy light…")
        try:
            dev = await fairy.find()
            self.client = BleakClient(dev, disconnected_callback=lambda c: self.status("Disconnected"))
            await self.client.connect()
            self.status(f"Connected to {getattr(dev, 'name', dev)}")
        except BaseException as e:
            self.status(f"Connect failed: {e}")

    def send(self, frame):
        asyncio.run_coroutine_threadsafe(self._send(frame), self.loop)

    async def _send(self, frame):
        if self.client and self.client.is_connected:
            await self.client.write_gatt_char(fairy.WRITE, frame, response=False)

    def close(self):
        if self.client:
            asyncio.run_coroutine_threadsafe(self.client.disconnect(), self.loop).result(3)

root = tk.Tk(); root.title("Fairy Lights"); root.geometry("360x460")
status = tk.StringVar(value="Not connected")
link = Link(lambda s: root.after(0, status.set, s))
hue, sat, bri, scene = tk.IntVar(value=0), tk.IntVar(value=100), tk.IntVar(value=100), tk.IntVar(value=1)

swatch = tk.Label(root, height=2)
def push_color(*_):
    r, g, b = colorsys.hsv_to_rgb(hue.get() / 360, sat.get() / 100, 1)
    swatch.config(bg="#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255)))
    link.send(fairy.hsv(hue.get(), sat.get() * 10, bri.get() * 10))

pad = dict(padx=14, pady=4, fill="x")
ttk.Label(root, textvariable=status).pack(**pad)
ttk.Button(root, text="Connect", command=link.connect).pack(**pad)
row = ttk.Frame(root); row.pack(**pad)
ttk.Button(row, text="On", command=lambda: link.send(fairy.power(True))).pack(side="left", padx=6)
ttk.Button(row, text="Off", command=lambda: link.send(fairy.power(False))).pack(side="left", padx=6)
swatch.pack(**pad)
for label, var, hi, lo in (("Colour", hue, 360, 0), ("Saturation", sat, 100, 0), ("Brightness", bri, 100, 1)):
    ttk.Label(root, text=label).pack(padx=14, anchor="w")
    ttk.Scale(root, from_=lo, to=hi, variable=var, command=lambda v, var=var: (var.set(int(float(v))), push_color())).pack(**pad)
ttk.Label(root, text="Scene").pack(padx=14, anchor="w")
row = ttk.Frame(root); row.pack(**pad)
ttk.Spinbox(row, from_=1, to=60, textvariable=scene, width=5).pack(side="left", padx=6)
ttk.Button(row, text="Play", command=lambda: link.send(fairy.scene(scene.get(), bri.get() * 10))).pack(side="left")
root.protocol("WM_DELETE_WINDOW", lambda: (link.close(), root.destroy()))
root.after(300, link.connect)
root.mainloop()
