#!/bin/bash
# Bootstrap Raspberry Pi 5 for:
#   • UVC capture stick on USB-A
#   • Bluetooth Classic HID (keyboard + mouse) over on-board radio
# Installs system deps, drops a bt-HID python bridge, creates systemd
# services, and reboots.  DOES NOT launch your vision agent; that stays
# separate.

set -euo pipefail
sudo -v   # prompt for sudo up-front

echo "=== 1. APT update & packages ==="
sudo apt update
sudo apt install -y \
  python3-venv python3-pip python3-dbus python3-evdev \
  bluez bluez-tools libbluetooth-dev \
  libatlas-base-dev libjpeg-dev libtiff6 libopenjp2-7 \
  libavcodec-dev libavformat-dev libswscale-dev libv4l-dev \
  libxvidcore-dev libx264-dev python3-opencv

echo "=== 2. Configure Bluetooth daemon ==="
sudo sed -i 's|^#Name = .*|Name = Pi-HID|' /etc/bluetooth/main.conf
sudo sed -i 's|^#Class = .*|Class = 0x002540|' /etc/bluetooth/main.conf
sudo sed -i 's|^#ControllerMode = .*|ControllerMode = bredr|' /etc/bluetooth/main.conf
sudo sed -i 's/^ExecStart=.*/ExecStart=\\/usr\\/lib\\/bluetooth\\/bluetoothd --noplugin=sap -P input/' \
  /lib/systemd/system/bluetooth.service
sudo systemctl daemon-reload
sudo systemctl restart bluetooth

echo "=== 3. Enable automatic pairing & discoverability ==="
sudo tee /etc/systemd/system/bt-agent.service >/dev/null <<'UNIT'
[Unit]
Description=Simple Bluetooth agent (NoInputNoOutput)
After=bluetooth.service
Requires=bluetooth.service

[Service]
Type=simple
ExecStart=/usr/bin/bluetoothctl --timeout=0 <<'BTCMD'
power on
discoverable on
pairable on
agent NoInputNoOutput
default-agent
system-alias Pi-HID
quit
BTCMD

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl enable bt-agent.service
sudo systemctl start  bt-agent.service

echo "=== 4. udev rule for /dev/uinput (evdev) ==="
echo 'KERNEL=="uinput", MODE="0666"' | sudo tee /etc/udev/rules.d/99-uinput.rules
sudo modprobe uinput   # now

echo "=== 5. Drop bt_hid_bridge.py ==="
sudo tee /usr/local/bin/bt_hid_bridge.py >/dev/null <<'PY'
#!/usr/bin/env python3
"""
Listens on localhost:5555 for 1-line commands:
  TAP x y        (norm 0-1)
  SWIPE dx dy
  TYPE text\nwith\nnewlines
Bridges them to Bluetooth HID via evdev → BlueZ input plugin.
"""
import socket, re, time
from evdev import UInput, ecodes as e

ui = UInput({e.EV_REL:[e.REL_X,e.REL_Y],
             e.EV_KEY:e.keys.values()}, name="Pi-HID")

def tap(x,y):
    # Simple relative jump toward target then click
    ui.write(e.EV_REL,e.REL_X,int((x-0.5)*200))
    ui.write(e.EV_REL,e.REL_Y,int((y-0.5)*200))
    ui.write(e.EV_KEY,e.BTN_LEFT,1); ui.syn(); time.sleep(0.05)
    ui.write(e.EV_KEY,e.BTN_LEFT,0); ui.syn()

def swipe(dx,dy):
    for _ in range(15):
        ui.write(e.EV_REL,e.REL_X,int(dx*10))
        ui.write(e.EV_REL,e.REL_Y,int(dy*10)); ui.syn(); time.sleep(0.02)

KEYMAP={**{c:getattr(e,f"KEY_{c.upper()}") for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"},
        **{str(i):getattr(e,f"KEY_{i}") for i in range(10)},
        ' ':e.KEY_SPACE,'\n':e.KEY_ENTER,',':e.KEY_COMMA,'.':e.KEY_DOT,'-':e.KEY_MINUS}

def type_text(txt):
    for ch in txt:
        kc=KEYMAP.get(ch.upper(),None)
        if not kc: continue
        ui.write(e.EV_KEY,kc,1); ui.syn(); ui.write(e.EV_KEY,kc,0); ui.syn(); time.sleep(0.03)

sock=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
sock.bind(("127.0.0.1",5555)); sock.listen(1)
print("bt_hid_bridge: listening on 127.0.0.1:5555")
while True:
    conn,_=sock.accept()
    with conn:
        for line in conn.makefile():
            m=line.strip().split(' ',2)
            if not m: continue
            cmd=m[0].upper()
            try:
                if cmd=="TAP":   tap(float(m[1]),float(m[2]))
                elif cmd=="SWIPE": swipe(float(m[1]),float(m[2]))
                elif cmd=="TYPE": type_text(m[1] if len(m)>1 else "")
            except Exception as ex:
                print("bad cmd:",line,ex)
PY
sudo chmod +x /usr/local/bin/bt_hid_bridge.py

echo "=== 6. Systemd service for HID bridge ==="
sudo tee /etc/systemd/system/pi-bthid.service >/dev/null <<'UNIT'
[Unit]
Description=Pi Bluetooth HID Bridge (GPIO agent)
After=bluetooth.service
Requires=bluetooth.service

[Service]
ExecStart=/usr/local/bin/bt_hid_bridge.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl enable pi-bthid.service
sudo systemctl start  pi-bthid.service

echo "=== 7. Python venv for vision agent ==="
mkdir -p ~/iControl
python3 -m venv ~/iControl/venv
source ~/iControl/venv/bin/activate
pip install --upgrade pip
pip install openai python-dotenv opencv-python

echo "=== ✔  All done.  Rebooting in 5 seconds ==="
sleep 5
sudo reboot
