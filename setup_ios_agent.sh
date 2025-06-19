#!/usr/bin/env bash
# Pi‑5 Bluetooth‑HID + UVC capture one‑shot installer (Bookworm 64‑bit)
# 2025‑06‑19  – v3  (robust)
# ‑ Installs system deps
# ‑ Configures BlueZ for "Pi‑HID" (discoverable, pairable, NoInputNoOutput)
# ‑ One‑shot bt‑init waits for controller before setting alias/agent
# ‑ TCP→uinput bridge (bt_hid_bridge.py) auto‑chmods /dev/uinput at runtime
# ‑ pi‑bthid.service waits for udev‑settle and bluetooth.target
# ‑ Creates ~/iControl/venv with OpenAI + OpenCV packages
set -euo pipefail
sudo -v  # prompt

### 1  Packages
sudo apt update
sudo apt install -y \
  python3-venv python3-pip python3-dbus python3-evdev \
  bluez bluez-tools libbluetooth-dev \
  libatlas-base-dev libjpeg-dev libtiff6 libopenjp2-7 \
  libavcodec-dev libavformat-dev libswscale-dev libv4l-dev \
  libxvidcore-dev libx264-dev python3-opencv git curl unzip

### 2  BlueZ config
CFG=/etc/bluetooth/main.conf
patch(){ grep -qE "^[#[:space:]]*$1" "$CFG" && sudo sed -i "s|^[#[:space:]]*$1.*|$1 = $2|" "$CFG" || echo "$1 = $2" | sudo tee -a "$CFG" >/dev/null; }
patch Name Pi-HID
patch Class 0x002540
patch ControllerMode bredr
patch DiscoverableTimeout 0
sudo sed -i 's|^ExecStart=.*|ExecStart=/usr/libexec/bluetooth/bluetoothd --noplugin=sap -P input|' \
  /lib/systemd/system/bluetooth.service
sudo systemctl daemon-reload
sudo rfkill unblock bluetooth
sudo systemctl restart bluetooth

### 3  bt_init.sh (waits for controller)
sudo tee /usr/local/sbin/bt_init.sh >/dev/null <<'SH'
#!/bin/bash
set -e
# wait until controller appears
for i in {1..10}; do
  hciconfig hci0 >/dev/null 2>&1 && break
  sleep 1
done
bluetoothctl <<EOF
power on
pairable on
discoverable on
agent NoInputNoOutput
default-agent
system-alias Pi-HID
quit
EOF
SH
sudo chmod +x /usr/local/sbin/bt_init.sh

sudo tee /etc/systemd/system/bt-agent.service >/dev/null <<'UNIT'
[Unit]
Description=Init BlueZ pairing settings (Pi-HID)
After=bluetooth.target
Requires=bluetooth.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/bt_init.sh

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now bt-agent.service

### 4  uinput permissions
echo 'KERNEL=="uinput", MODE="0666"' | sudo tee /etc/udev/rules.d/99-uinput.rules
sudo udevadm control --reload-rules
sudo modprobe uinput
sudo udevadm trigger -v /dev/uinput || true

### 5  Python venv & packages
mkdir -p ~/iControl
python3 -m venv ~/iControl/venv
source ~/iControl/venv/bin/activate
pip install --upgrade pip
pip install openai python-dotenv opencv-python evdev dbus-next

### 6  TCP→uinput bridge
sudo tee /usr/local/bin/bt_hid_bridge.py >/dev/null <<'PY'
#!/usr/bin/env python3
import socket, time, os, sys
from evdev import UInput, ecodes as e
# ensure /dev/uinput rw
try:
    os.chmod('/dev/uinput',0o666)
except PermissionError:
    pass
# valid keycodes for keyboard + mouse
BASE_KEYS=(
  [ e.BTN_LEFT ]
  + list(range(e.KEY_A, e.KEY_Z+1))
  + list(range(e.KEY_0, e.KEY_9+1))
  + [e.KEY_SPACE, e.KEY_ENTER, e.KEY_COMMA, e.KEY_DOT, e.KEY_MINUS]
)
ui = UInput({e.EV_REL:[e.REL_X,e.REL_Y],
             e.EV_KEY: BASE_KEYS}, name='Pi-HID')

def tap(x,y):
    ui.write(e.EV_REL,e.REL_X,int((x-0.5)*200))
    ui.write(e.EV_REL,e.REL_Y,int((y-0.5)*200))
    ui.write(e.EV_KEY,e.BTN_LEFT,1); ui.syn(); time.sleep(0.05)
    ui.write(e.EV_KEY,e.BTN_LEFT,0); ui.syn()

def swipe(dx,dy):
    for _ in range(15):
        ui.write(e.EV_REL,e.REL_X,int(dx*10))
        ui.write(e.EV_REL,e.REL_Y,int(dy*10)); ui.syn(); time.sleep(0.02)
KEY={**{c:getattr(e,f'KEY_{c.upper()}') for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'},
     **{str(i):getattr(e,f'KEY_{i}') for i in range(10)},
     ' ':e.KEY_SPACE,'\n':e.KEY_ENTER,',':e.KEY_COMMA,'.':e.KEY_DOT,'-':e.KEY_MINUS}

def type_text(t):
    for ch in t:
        kc=KEY.get(ch)
        if kc:
            ui.write(e.EV_KEY,kc,1); ui.syn(); ui.write(e.EV_KEY,kc,0); ui.syn(); time.sleep(0.03)

def main():
    s=socket.socket(); s.bind(('127.0.0.1',5555)); s.listen(1)
    print('bt_hid_bridge listening on 127.0.0.1:5555')
    while True:
        c,_=s.accept()
        with c,c.makefile() as f:
            for l in f:
                cmd,*a=l.strip().split(' ',2)
                try:
                    if cmd=='TAP': tap(float(a[0]),float(a[1]))
                    elif cmd=='SWIPE': swipe(float(a[0]),float(a[1]))
                    elif cmd=='TYPE': type_text(a[0] if a else '')
                except Exception as ex:
                    print('bad cmd',l.strip(),ex)
if __name__=='__main__':
    main()
PY
sudo chmod +x /usr/local/bin/bt_hid_bridge.py

### 7  pi-bthid.service (waits for udev settle)
VENVPY=/home/aollman/iControl/venv/bin/python3
sudo tee /etc/systemd/system/pi-bthid.service >/dev/null <<UNIT
[Unit]
Description=Pi Bluetooth HID Bridge (TCP→uinput)
After=bluetooth.target systemd-udev-settle.service
Requires=bluetooth.target

[Service]
ExecStart=${VENVPY} /usr/local/bin/bt_hid_bridge.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now pi-bthid.service

### done
echo '✔ Setup complete — rebooting in 5 s'; sleep 5; sudo reboot
