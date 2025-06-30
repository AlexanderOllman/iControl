#!/usr/bin/env python3
"""Pi‑5 Vision→iPhone agent (video via capture stick, input via Bluetooth HID)

* Captures frames from the Macrosilicon UVC dongle (`--video-index`).
* Sends TAP / SWIPE / TYPE commands to the local **Bluetooth HID bridge**
  running at 127.0.0.1:5555 (installed by setup script). The bridge converts
  those commands into uinput events which BlueZ forwards to the paired iPhone.
* Waits until the TCP bridge socket is reachable (user has paired phone and
  bridge is running) before starting the GPT loop.

Run:
    python3 auto_ios_agent.py --task "Open Notes and type hello" --video-index 2
"""
from __future__ import annotations
import os, sys, time, json, base64, argparse, socket, cv2, re, openai
from typing import List, Dict

MODEL = "gpt-4o-mini"
PROMPT = (
  "You are an iOS automation agent. Look at the screenshot and the task. "
  "THINK SILENTLY, then output ONLY valid JSON for the next UI action. "
  "Schema: {\"type\":tap|doubleTap|swipe|type|none|done, \"x\":0-1, \"y\":0-1, "
  "\"dx\":0-1, \"dy\":0-1, \"text\":\"…\"}. "
  "Use type when keyboard input is needed. Return {\"type\":\"done\"} when the task is complete."
)
R = re.compile(r"\{.*?\}", re.S)
BRIDGE_HOST, BRIDGE_PORT = "127.0.0.1", 5555

# ── bridge helpers ──

def connect_bridge(timeout: int = 60) -> socket.socket:
    start = time.time()
    while time.time() - start < timeout:
        try:
            s = socket.create_connection((BRIDGE_HOST, BRIDGE_PORT), timeout=2)
            print("[✓] Connected to HID bridge")
            return s
        except (ConnectionRefusedError, OSError):
            print("[wait] HID bridge not ready; pair phone and start bridge …", end="\r")
            time.sleep(2)
    sys.exit("Bridge socket not reachable — is pi-bthid.service running?")


def send(cmd: str, sock: socket.socket):
    sock.sendall((cmd + "\n").encode())

# ── GPT helper ──

def next_action(img64: str, task: str) -> dict:
    msgs = [{"role": "system", "content": PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": f"Task: {task}"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img64}"}}
            ]}]
    txt = openai.chat.completions.create(model=MODEL, messages=msgs, temperature=0, max_tokens=120).choices[0].message.content
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        return json.loads(R.search(txt).group())

# ── main ──

def main():
    if not os.getenv("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY missing")

    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="Open Notes and type hello")
    ap.add_argument("--video-index", type=int, default=2)
    ap.add_argument("--interval", type=float, default=1.0)
    args = ap.parse_args()

    # connect to Bluetooth HID bridge
    sock = connect_bridge()

    cap = cv2.VideoCapture(args.video_index)
    if not cap.isOpened():
        sys.exit("No /dev/video device (check --video-index)")

    while True:
        t0 = time.time()
        ok, frame = cap.read()
        if not ok:
            continue
        _, buf = cv2.imencode(".png", frame)
        act = next_action(base64.b64encode(buf).decode(), args.task)
        print(act)
        tp = act.get("type")
        if tp == "done":
            break
        if tp == "tap":
            send(f"TAP {act['x']:.3f} {act['y']:.3f}", sock)
        elif tp == "doubleTap":
            send(f"TAP {act['x']:.3f} {act['y']:.3f}", sock)
            time.sleep(0.1)
            send(f"TAP {act['x']:.3f} {act['y']:.3f}", sock)
        elif tp == "swipe":
            send(f"SWIPE {act['dx']:.3f} {act['dy']:.3f}", sock)
        elif tp == "type":
            txt = act.get("text", "").replace("\n", "\\n")
            send(f"TYPE {txt}", sock)
        dt = time.time() - t0
        if dt < args.interval:
            time.sleep(args.interval - dt)

    cap.release(); sock.close()

if __name__ == "__main__":
    main()
