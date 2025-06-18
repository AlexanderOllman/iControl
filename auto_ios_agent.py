#!/usr/bin/env python3
"""
auto_ios_agent_pi5.py
=====================
💡 **Raspberry Pi 5 all-in-one iPhone agent** - no external MCU needed.

* Pi 5's **USB-A ports** run the HDMI→USB3 capture stick (host).
* Pi 5's **USB-C port** (gadget mode) appears to the iPhone as a wired
  **keyboard + absolute-touch digitiser** using the Linux `libcomposite`
  framework (`/dev/hidg0`, `/dev/hidg1`).

Setup summary
-------------
1. **Enable gadget mode** (once):
   ```bash
   # /boot/config.txt
   dtoverlay=dwc2
   # /boot/cmdline.txt  (append right after root=... rw)
   modules-load=dwc2
   ```
2. **Mount configfs & run the gadget script** (idempotent):
   ```bash
   sudo modprobe libcomposite
   sudo mount -t configfs none /sys/kernel/config
   sudo /usr/bin/iphone_hid_gadget.sh    # script from earlier message
   ```
   On success `/dev/hidg0` (keyboard) and `/dev/hidg1` (touch) appear.
3. **Cable** - Pi 5 USB-C (device) → iPhone; capture stick stays in any USB-A.
4. **Run this agent**:
   ```bash
   python3 auto_ios_agent_pi5.py --video-index 2 \
     --task "Open Notes and type hello"
   ```
"""
from __future__ import annotations
import os, sys, cv2, time, json, base64, textwrap, argparse, re
from typing import Dict, List
import openai
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# OpenAI prompt
# ---------------------------------------------------------------------------
OPENAI_MODEL = "gpt-4o-mini"
SYSTEM_PROMPT = textwrap.dedent(
    """
    You are an expert iOS automation agent. Given the current screenshot and
    the high-level task, decide the next atomic UI action **and explain why**.

    Reply ONLY with JSON:
      {"type":"tap"|"doubleTap"|"swipe"|"type"|"none"|"done",
       "x":0-1,"y":0-1,        "dx":0-1,"dy":0-1, "text":"…",
       "explanation":"why this action"}
    """
)

# ---------------------------------------------------------------------------
# Gadget HID helpers (boot keyboard + abs touch)
# ---------------------------------------------------------------------------
KBD = open('/dev/hidg0', 'wb', buffering=0)
TOUCH = open('/dev/hidg1', 'wb', buffering=0)

KEY_MAP: Dict[str, int] = {**{c:0x04+i for i,c in enumerate("abcdefghijklmnopqrstuvwxyz")},
                          **{str(i):0x1E+i for i in range(10)},
                          " ":0x2C,"\n":0x28,",":0x36,".":0x37,"-":0x2D,"/":0x38}

def send_key(ch: str):
    kc = KEY_MAP.get(ch.lower())
    if kc is None: return
    # 8-byte boot report [mods, reserved, 6×keycodes]
    press = bytes([0,0,kc,0,0,0,0,0])
    KBD.write(press); KBD.flush(); time.sleep(0.04)
    KBD.write(b"\x00"*8); KBD.flush()

def type_text(text: str):
    for ch in text:
        send_key(ch)
        time.sleep(0.02)

def tap(x: float, y: float):
    x_abs = int(x*32767) & 0x7FFF
    y_abs = int(y*32767) & 0x7FFF
    TOUCH.write(x_abs.to_bytes(2,'little') + y_abs.to_bytes(2,'little'))
    TOUCH.flush()
    time.sleep(0.05)
    TOUCH.write(b"\x00\x00\x00\x00")  # lift
    TOUCH.flush()

def swipe(dx: float, dy: float):
    steps=15
    for _ in range(steps):
        tap(0.5+dx/steps, 0.5+dy/steps)
        time.sleep(0.02)

# ---------------------------------------------------------------------------
# GPT wrapper
# ---------------------------------------------------------------------------
import re, json

def _json_from(txt:str):
    m=re.search(r"\{.*\}",txt,re.S)
    if not m: raise ValueError("No JSON in GPT reply")
    return json.loads(m.group(0))

def decide(img_b64:str,task:str,history:List[Dict]):
    msgs=[{"role":"system","content":SYSTEM_PROMPT},*history,
          {"role":"user","content":[{"type":"text","text":f"Task: {task}"},
              {"type":"image_url","image_url":{"url":f"data:image/png;base64,{img_b64}"}}]}]
    rsp=openai.chat.completions.create(model=OPENAI_MODEL,messages=msgs,temperature=0,max_tokens=200)
    txt=rsp.choices[0].message.content.strip()
    history.append({"role":"assistant","content":txt})
    try:
        return json.loads(txt)
    except Exception:
        return _json_from(txt)

# ---------------------------------------------------------------------------
# Frame grab
# ---------------------------------------------------------------------------

def grab(cap):
    ok,frame=cap.read()
    if not ok: raise RuntimeError("No frame")
    _,buf=cv2.imencode(".png",frame)
    return base64.b64encode(buf).decode()

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    load_dotenv()
    pa=argparse.ArgumentParser()
    pa.add_argument("--task",default="Open Notes and type hello")
    pa.add_argument("--video-index",type=int,default=2)
    pa.add_argument("--interval",type=float,default=1.0)
    args=pa.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY not set")

    cap=cv2.VideoCapture(args.video_index)
    if not cap.isOpened():
        sys.exit("Cannot open capture device - check --video-index")

    hist:List[Dict]=[]
    try:
        while True:
            t0=time.time()
            img=grab(cap)
            act=decide(img,args.task,hist)
            print("[GPT]",act.get("explanation","<exp missing>"),"→",{k:v for k,v in act.items() if k!="explanation"})
            tp=act.get("type")
            if tp=="done": break
            if tp=="none": time.sleep(args.interval); continue
            if tp in ("tap","doubleTap"):
                tap(float(act["x"]),float(act["y"]))
                if tp=="doubleTap":
                    time.sleep(0.1);
                    tap(float(act["x"]),float(act["y"]))
            elif tp=="swipe":
                swipe(float(act["dx"]),float(act["dy"]))
            elif tp=="type":
                type_text(act.get("text",""))
            dt=time.time()-t0
            if dt<args.interval:
                time.sleep(args.interval-dt)
    finally:
        cap.release(); KBD.close(); TOUCH.close()

if __name__=="__main__":
    main()
