#!/usr/bin/env bash
# Pi‑5 Bluetooth‑HID + UVC capture one‑shot installer (Bookworm 64‑bit)
# 2025‑06‑19  – v6: ensure SDP HID record via sdptool add HID
set -euo pipefail
sudo -v

############################ 1  Packages ################################
sudo apt update
sudo apt install -y python3-venv python3-pip python3-dbus python3-evdev \
  bluez bluez-tools libbluetooth-dev libatlas-base-dev libjpeg-dev libtiff6 \
  libopenjp2-7 libavcodec-dev libavformat-dev libswscale-dev libv4l-dev \
  libxvidcore-dev libx264-dev python3-opencv git curl unzip

############################ 2  BlueZ ###################################
CFG=/etc/bluetooth/main.conf
patch(){
  local k=$1 v=$2
  grep -qE "^[#[:space:]]*$k" "$CFG" &&
    sudo sed -i "s|^[#[:space:]]*$k.*|$k = $v|" "$CFG" ||
    echo "$k = $v" | sudo tee -a "$CFG" >/dev/null
}
patch Name Pi-HID
patch Class 0x002580                  # mouse‑only HID → no PIN dialog
patch ControllerMode bredr
patch DiscoverableTimeout 0

# ExecStart: input plugin *enabled*, sap disabled
sudo sed -i -e 's|^ExecStart=.*|ExecStart=/usr/libexec/bluetooth/bluetoothd --noplugin=sap -P input|' \
           -e 's| --noplugin=input||g' \
  /lib/systemd/system/bluetooth.service

############################ 2.1  Kernel hidp/uhid (persist) ###########
sudo modprobe hidp uhid
for mod in hidp uhid; do grep -qxF "$mod" /etc/modules || echo "$mod" | sudo tee -a /etc/modules; done

sudo systemctl daemon-reload
sudo rfkill unblock bluetooth
sudo systemctl restart bluetooth

# force‑register SDP HID record (BlueZ sometimes drops it)
sudo sdptool add HID || true

############################ 3  bt_init.sh ###############################
sudo tee /usr/local/sbin/bt_init.sh >/dev/null <<'SH'
#!/bin/bash
set -e
# wait until controller appears
for _ in {1..10}; do hciconfig hci0 >/dev/null 2>&1 && break; sleep 1; done
bluetoothctl <<EOF
power on
pairable on
discoverable on
agent NoInputNoOutput
default-agent
# ── BLE HID advertising (mouse) ──
menu advertise
appearance 962                              # Generic Mouse
uuids 00001812-0000-1000-8000-00805f9b34fb   # HID Service
back
advertise on                                # start LE advertising
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

############################ 4  uinput permissions #######################
echo 'KERNEL=="uinput", MODE="0666"' | sudo tee /etc/udev/rules.d/99-uinput.rules
sudo udevadm control --reload-rules
sudo modprobe uinput
sudo udevadm trigger /dev/uinput || true

############################ 5  Python venv ##############################
mkdir -p ~/iControl
python3 -m venv ~/iControl/venv
source ~/iControl/venv/bin/activate
pip install -q --upgrade pip
pip install -q openai python-dotenv opencv-python evdev dbus-next

deactivate

############################ 6  Bridge script ############################
sudo tee /usr/local/bin/bt_hid_bridge.py >/dev/null <<'PY'
#!/usr/bin/env python3
"""TCP(5555) → uinput Bluetooth HID bridge (mouse + basic keys)."""
import os, socket, time
from evdev import UInput, ecodes as e

# ensure /dev/uinput writable
try:
    os.chmod('/dev/uinput', 0o666)
except PermissionError:
    pass

BASE_KEYS=[e.BTN_LEFT,*range(e.KEY_A,e.KEY_Z+1),*range(e.KEY_0,e.KEY_9+1),
           e.KEY_SPACE,e.KEY_ENTER,e.KEY_COMMA,e.KEY_DOT,e.KEY_MINUS]
ui=UInput({e.EV_REL:[e.REL_X,e.REL_Y],e.EV_KEY:BASE_KEYS},name='Pi-HID')

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

def type_text(t:str):
    for ch in t:
        kc=KEY.get(ch);
        if kc:
            ui.write(e.EV_KEY,kc,1); ui.syn(); ui.write(e.EV_KEY,kc,0); ui.syn(); time.sleep(0.03)

def main():
    s=socket.socket(); s.bind(('127.0.0.1',5555)); s.listen(1)
    print('bt_hid_bridge listening on 127.0.0.1:5555')
    while True:
        c,_=s.accept();
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

############################ 7  Service ##############################
VENVPY=/home/aollman/iControl/venv/bin/python3
sudo tee /etc/systemd/system/pi-bthid.service >/dev/null <<UNIT
[Unit]
Description=Pi Bluetooth HID Bridge (TCP→uinput)
After=bluetooth.target systemd-udev-settle.service
Requires=bluetooth.target

[Service]
ExecStartPre=/usr/bin/modprobe hidp
ExecStartPre=/usr/bin/modprobe uhid
ExecStart=${VENVPY} /usr/local/bin/bt_hid_bridge.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now pi-bthid.service

############################ Finish #############################
printf '\n✔ Setup complete – rebooting in 5 s\n'; sleep 5; sudo reboot
