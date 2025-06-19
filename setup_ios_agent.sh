#!/bin/bash
# setup_bt_ios_agent_pi5.sh  –  configure Pi-5 for
#   • HDMI→USB capture stick (video)
#   • Bluetooth Classic HID (input)
#   • TCP bridge at 127.0.0.1:5555 for TAP/SWIPE/TYPE
set -euo pipefail
sudo -v    # prompt for sudo password up-front

echo "=== 1. APT update & base packages ==="
sudo apt update
sudo apt install -y \
  python3-venv python3-pip python3-dbus python3-evdev \
  bluez bluez-tools libbluetooth-dev \
  libatlas-base-dev libjpeg-dev libtiff6 libopenjp2-7 \
  libavcodec-dev libavformat-dev libswscale-dev libv4l-dev \
  libxvidcore-dev libx264-dev python3-opencv git curl unzip

echo "=== 2. Configure BlueZ daemon (Pi-HID) ==="
cfg=/etc/bluetooth/main.conf
patch_bluez () {
  local key="$1" val="$2"
  if grep -qE "^[#[:space:]]*${key}[[:space:]]*=" "$cfg"; then
    sudo sed -i "s|^[#[:space:]]*${key}[[:space:]]*=.*|${key} = ${val}|" "$cfg"
  else
    echo "${key} = ${val}" | sudo tee -a "$cfg" >/dev/null
  fi
}
patch_bluez "Name"            "Pi-HID"
patch_bluez "Class"           "0x002540"   # Peripheral | Keyboard | Pointing
patch_bluez "ControllerMode"  "bredr"      # Classic (not LE for now)

# Ensure bluetoothd loads 'input' profile
sudo sed -i \
  's|^ExecStart=.*|ExecStart=/usr/libexec/bluetooth/bluetoothd --noplugin=sap -P input|' \
  /lib/systemd/system/bluetooth.service
sudo systemctl daemon-reload
sudo systemctl restart  bluetooth.service

echo "=== 3. Auto-pairing /discoverable agent (bt-agent.service) ==="
sudo tee /etc/systemd/system/bt-agent.service >/dev/null <<'UNIT'
[Unit]
Description=Simple Bluetooth agent (NoInputNoOutput, always discoverable)
After=bluetooth.service
Requires=bluetooth.service

[Service]
Type=exec
ExecStart=/usr/bin/bluetoothctl --timeout=0 <<'BTC'
power on
discoverable on
pairable on
agent NoInputNoOutput
default-agent
system-alias Pi-HID
quit
BTC

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl enable bt-agent.service
sudo systemctl start  bt-agent.service

echo "=== 4. udev rule + module for /dev/uinput ==="
echo 'KERNEL=="uinput", MODE="0666"' | sudo tee /etc/udev/rules.d/99-uinput.rules
echo "uinput" | sudo tee -a /etc/modules >/dev/null
sudo modprobe uinput

echo "=== 5. Drop TCP→uinput Bluetooth HID bridge ==="
sudo tee /usr/local/bin/bt_hid_bridge.py >/dev/null <<'PY'
#!/usr/bin/env python3
import socket,time
from evdev import UInput, ecodes as e

ui = UInput({e.EV_REL:[e.REL_X,e.REL_Y],
             e.EV_KEY:list(e.keys.values())}, name="Pi-HID")

def tap(x,y):
    ui.write(e.EV_REL,e.REL_X,int((x-0.5)*200))
    ui.write(e.EV_REL,e.REL_Y=int((y-0.5)*200))
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
        kc=KEYMAP.get(ch.upper())
        if kc: ui.write(e.EV_KEY,kc,1); ui.syn(); ui.write(e.EV_KEY,kc,0); ui.syn(); time.sleep(0.03)

sock=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
sock.bind(("127.0.0.1",5555)); sock.listen(1)
print("bt_hid_bridge: waiting on 127.0.0.1:5555")
while True:
    conn,_=sock.accept()
    with conn:
        for line in conn.makefile():
            cmds=line.strip().split(' ',2)
            if not cmds: continue
            try:
                if cmds[0]=="TAP":   tap(float(cmds[1]),float(cmds[2]))
                elif cmds[0]=="SWIPE": swipe(float(cmds[1]),float(cmds[2]))
                elif cmds[0]=="TYPE": type_text(cmds[1] if len(cmds)>1 else "")
            except Exception as err:
                print("bad cmd",line,err)
PY
sudo chmod +x /usr/local/bin/bt_hid_bridge.py

echo "=== 6. systemd unit for HID bridge ==="
sudo tee /etc/systemd/system/pi-bthid.service >/dev/null <<'UNIT'
[Unit]
Description=Pi Bluetooth HID Bridge (TCP→uinput)
After=bluetooth.service bt-agent.service
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

echo "=== ✔  Setup complete — rebooting in 5 s ==="
sleep 5
sudo reboot
