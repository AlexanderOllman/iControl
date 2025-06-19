#!/usr/bin/env bash
# Pi‑5 Bluetooth‑HID + UVC capture one‑shot installer (Bookworm 64‑bit)
# ‑ Installs system deps
# ‑ Configures BlueZ for "Pi‑HID" (discoverable, pairable, NoInputNoOutput)
# ‑ Deploys bt_init.sh (+ systemd unit)  → makes adapter visible at boot
# ‑ Deploys TCP→uinput bridge (bt_hid_bridge.py) inside python venv
# ‑ Creates pi‑bthid.service using venv’s python
# ‑ Creates ~/iControl/venv with OpenAI + OpenCV packages
# After reboot:  pair iPhone ▸ Pi‑HID, then run auto_ios_agent.py
set -euo pipefail
sudo -v   # ask for sudo pwd upfront

### 1  APT
sudo apt update
sudo apt install -y \
  python3-venv python3-pip python3-dbus python3-evdev \
  bluez bluez-tools libbluetooth-dev \
  libatlas-base-dev libjpeg-dev libtiff6 libopenjp2-7 \
  libavcodec-dev libavformat-dev libswscale-dev libv4l-dev \
  libxvidcore-dev libx264-dev python3-opencv git curl unzip

### 2  BlueZ main.conf tweaks
CFG=/etc/bluetooth/main.conf
patch_bluez(){
  local k="$1" v="$2"
  if grep -qE "^[#[:space:]]*${k}[[:space:]]*=" "$CFG"; then
    sudo sed -i "s|^[#[:space:]]*${k}[[:space:]]*=.*|${k} = ${v}|" "$CFG"
  else
    echo "${k} = ${v}" | sudo tee -a "$CFG" >/dev/null
  fi
}
patch_bluez Name           "Pi-HID"
patch_bluez Class          "0x002540"   # Peripheral+KB/Mouse
patch_bluez ControllerMode "bredr"
patch_bluez DiscoverableTimeout 0

# bluetoothd with input plugin
sudo sed -i 's|^ExecStart=.*|ExecStart=/usr/libexec/bluetooth/bluetoothd --noplugin=sap -P input|' \
  /lib/systemd/system/bluetooth.service
sudo systemctl daemon-reload
sudo rfkill unblock bluetooth
sudo systemctl restart bluetooth.service

### 3  one‑shot bt_init.sh
sudo tee /usr/local/sbin/bt_init.sh >/dev/null <<'SH'
#!/bin/bash
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
Description=Bluetooth one-shot init (Pi-HID)
After=bluetooth.service
Requires=bluetooth.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/bt_init.sh

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now bt-agent.service

### 4  uinput access
echo 'KERNEL=="uinput", MODE="0666"' | sudo tee /etc/udev/rules.d/99-uinput.rules
sudo udevadm control --reload-rules
sudo modprobe uinput
sudo udevadm trigger -v /dev/uinput || true

### 5  Python venv + bridge
mkdir -p ~/iControl
python3 -m venv ~/iControl/venv
source ~/iControl/venv/bin/activate
pip install --upgrade pip
pip install openai python-dotenv opencv-python evdev dbus-next

# TCP→uinput bridge (fixed syntax)
sudo tee /usr/local/bin/bt_hid_bridge.py >/dev/null <<'PY'
#!/usr/bin/env python3
import socket, time
from evdev import UInput, ecodes as e

ui = UInput({e.EV_REL: [e.REL_X, e.REL_Y],
             e.EV_KEY: list(e.keys.values())}, name="Pi-HID")

# ── basic actions ──

def tap(x: float, y: float):
    ui.write(e.EV_REL, e.REL_X, int((x - 0.5) * 200))
    ui.write(e.EV_REL, e.REL_Y, int((y - 0.5) * 200))
    ui.write(e.EV_KEY, e.BTN_LEFT, 1); ui.syn(); time.sleep(0.05)
    ui.write(e.EV_KEY, e.BTN_LEFT, 0); ui.syn()

def swipe(dx: float, dy: float):
    for _ in range(15):
        ui.write(e.EV_REL, e.REL_X, int(dx * 10))
        ui.write(e.EV_REL, e.REL_Y, int(dy * 10))
        ui.syn(); time.sleep(0.02)

KEY = {**{c: getattr(e, f"KEY_{c.upper()}") for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"},
       **{str(i): getattr(e, f"KEY_{i}") for i in range(10)},
       ' ': e.KEY_SPACE, '\n': e.KEY_ENTER,
       ',': e.KEY_COMMA, '.': e.KEY_DOT, '-': e.KEY_MINUS}

def type_text(txt: str):
    for ch in txt:
        kc = KEY.get(ch)
        if kc:
            ui.write(e.EV_KEY, kc, 1); ui.syn()
            ui.write(e.EV_KEY, kc, 0); ui.syn(); time.sleep(0.03)

# ── socket listener ──

sock = socket.socket()
sock.bind(("127.0.0.1", 5555))
sock.listen(1)
print("bt_hid_bridge listening on 127.0.0.1:5555")
while True:
    conn, _ = sock.accept()
    with conn, conn.makefile() as f:
        for line in f:
            cmd, *args = line.strip().split(' ', 2)
            try:
                if cmd == "TAP":
                    tap(float(args[0]), float(args[1]))
                elif cmd == "SWIPE":
                    swipe(float(args[0]), float(args[1]))
                elif cmd == "TYPE":
                    type_text(args[0] if args else "")
            except Exception as ex:
                print("bad cmd", line.strip(), ex)
PY
sudo chmod +x /usr/local/bin/bt_hid_bridge.py

### 6  systemd unit (uses venv python)
VENVPY=/home/aollman/iControl/venv/bin/python3
sudo tee /etc/systemd/system/pi-bthid.service >/dev/null <<UNIT
[Unit]
Description=Pi Bluetooth HID Bridge (TCP→uinput)
After=bluetooth.service bt-agent.service
Requires=bluetooth.service

[Service]
ExecStart=${VENVPY} /usr/local/bin/bt_hid_bridge.py
Environment=PYTHONUNBUFFERED=1
Restart=on-failure

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now pi-bthid.service

### done
echo "✔ Setup complete — rebooting in 5 s"; sleep 5; sudo reboot
