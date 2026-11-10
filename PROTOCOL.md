# Hello Fairy Bluetooth protocol

What this project has worked out about the lights, from a Bluetooth capture of the vendor app and from reading the
app's code. One string was tested (model `BSL84`, firmware `4.6.3`). Treat anything not listed as unknown.

## Connection

- BLE service `49535343-fe7d-4ae5-8fa9-9fafd205e455` (a "transparent UART" service).
- Write commands (write-without-response) to `49535343-8841-43f4-a8d4-ecbe34729bb3`.
- Replies arrive as notifications on `49535343-1e4d-4bd9-ba61-23c647249616`.
- Request an MTU of 247 before sending pictures: their packets are 242 bytes.
- One connection at a time. The advertised name starts with `Hello Fairy`.

## Frames

Every command is `AA TYPE LEN payload... SUM`, where `SUM` is the low byte of the sum of all earlier bytes.

| Type | Meaning | Payload |
|---|---|---|
| `00` | device info (reply has firmware, model, LED count, grid hints) | none |
| `02` | power | `00` off, `01` on |
| `03` | light mode | `01 H(2) S(2) V(2)` solid colour (H 0-360, S and V 0-1000, big-endian); `02 SCENE V(2)` built-in scene |
| `d0` | picture settings | `direction brightness speed kind` |
| `d7` | frame bookkeeping | `frame state` (0 new, 1 edit, 2 save, 3 delete) |
| `da` | pixel packet | `frame {led(2) colour}...` |
| `d3`, `d4`, `db` | text with the light's built-in font | see `text_frames` in `fairy.py` |
| `d9` | save text slot | `slot 02` |

## Pictures and animations

- The tested light reports 800 LEDs, 20 per column: a 40 x 20 grid, LED index = `x * 20 + y`.
- Colours are one byte each: hue / 2 (0-179), `ff` white, `fe` off. Sending true-colour packets makes the light
  drop the connection.
- A frame is 800 LEDs: 11 packets of up to 79 LEDs. Send them about 50 ms apart.
- Sequence for an animation: `d0` kind 6 (one-byte colours), `d0` kind 7 (new animation), `d7` new frame 1,
  `d0` kind 0 (edit); then per frame its `da` packets, with `d7` save/new between frames; `d7` save for the last frame;
  `d0` kind 4 (save); `d0` kind 2 (run). A single picture uses kind 3 and kind 1 instead.
- The vendor app's own editor stops at 5 frames. Its preset animations for 40 x 20 products have up to 72 frames, but
  only animations of up to 7 frames have been tried on a real light here, so the light's real limit is unknown.
- `d0` directions: 0 static, 1 up, 2 down, 3 left, 4 right, 5 flash, 6 breath.
- Static pictures flicker slightly whatever the speed value is. That looks like the controller, not the protocol.

## Checking your own work

`fairy.py` writes these frames, and `android/builder`'s unit tests check the Kotlin sender byte for byte against files
written by the Python one. Golden files are in `android/builder/src/test/resources/`.
