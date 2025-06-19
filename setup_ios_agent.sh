#!/usr/bin/env bash
# Pi‑5 Classic‑Bluetooth HID (keyboard+mouse) with AUTO‑PIN entry
# Bookworm 64‑bit – vA (2025‑06‑19)
# ‑ Installs deps, enables BR/EDR keyboard+mouse SDP record
# ‑ Starts bt_autokey.py that receives the 6‑digit pass‑key from BlueZ and
#   types it via /dev/uinput so iOS pairing succeeds automatically.
set -euo pipefail
sudo -v

################################ 1  Packages #################################
sudo apt update
sudo apt install -y python3-venv python3-pip python3-dbus python3-evdev \
  bluez bluez-tools libbluetooth-dev git

################################ 2  BlueZ ####################################
CFG=/etc/bluetooth/main.conf
patch(){ grep -qE "^[#[:space:]]*$1" "$CFG" && \
         sudo sed -i "s|^[#[:space:]]*$1.*|$1 = $2|" "$CFG" || \
         echo "$1 = $2" | sudo tee -a "$CFG" >/dev/null; }
patch Name Pi-HID
patch Class 0x002540       # Peripheral | Keyboard | Pointing
patch ControllerMode bredr
patch DiscoverableTimeout 0

sudo sed -i 's|^ExecStart=.*|ExecStart=/usr/libexec/bluetooth/bluetoothd --noplugin=sap -P input|' \
  /lib/systemd/system/bluetooth.service

################################ 2.1 Kernel hidp/uhid ########################
sudo modprobe hidp uhid
for m in hidp uhid; do grep -qxF "$m" /etc/modules || echo "$m" | sudo tee -a /etc/modules; done
sudo systemctl daemon-reload
sudo rfkill unblock bluetooth
sudo systemctl restart bluetooth

# Classic HID SDP record
sudo sdptool add HID || true

################################ 3  bt_init.sh (KeyboardDisplay agent) #######
sudo tee /usr/local/sbin/bt_init.sh >/dev/null <<'SH'
#!/bin/bash
set -e
for _ in {1..10}; do hciconfig hci0 >/dev/null 2>&1 && break; sleep 1; done
bluetoothctl <<EOF
power on
pairable on
discoverable on
agent KeyboardDisplay
default-agent
system-alias Pi-HID
quit
EOF
SH
sudo chmod +x /usr/local/sbin/bt_init.sh

sudo tee /etc/systemd/system/bt-agent.service >/dev/null <<'UNIT'
[Unit]
Description=Init BlueZ (KeyboardDisplay agent)
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

################################ 4  uinput perms ##############################
echo 'KERNEL=="uinput", MODE="0666"' | sudo tee /etc/udev/rules.d/99-uinput.rules
sudo modprobe uinput
sudo udevadm trigger /dev/uinput || true

################################ 5  Python venv ###############################
mkdir -p ~/iControl
python3 -m venv ~/iControl/venv
source ~/iControl/venv/bin/activate
pip install -q --upgrade pip
pip install -q evdev dbus-python gi

deactivate

################################ 6  bt_autokey.py #############################
sudo tee /usr/local/bin/bt_autokey.py >/dev/null <<'PY'
#!/usr/bin/env python3
"""Auto‑types the 6‑digit pass‑key shown on iOS during Classic‑HID pairing."""
import time, dbus, dbus.mainloop.glib
from gi.repository import GLib
from evdev import UInput, ecodes as e

UI=UInput({e.EV_KEY:[e.KEY_ENTER,*[getattr(e,f'KEY_{i}') for i in range(10)]]}, name='AutoKey')
KEY={str(i):getattr(e,f'KEY_{i}') for i in range(10)}

def type_code(code:str):
    for ch in code:
        UI.write(e.EV_KEY, KEY[ch], 1); UI.syn(); UI.write(e.EV_KEY, KEY[ch], 0); UI.syn(); time.sleep(0.05)
    UI.write(e.EV_KEY, e.KEY_ENTER, 1); UI.syn(); UI.write(e.EV_KEY, e.KEY_ENTER, 0); UI.syn()

class Agent(dbus.service.Object):
    @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='')
    def AuthorizeService(self, dev, uuid): pass

    @dbus.service.method('org.bluez.Agent1', in_signature='o', out_signature='')
    def RequestAuthorization(self, dev): pass

    @dbus.service.method('org.bluez.Agent1', in_signature='ouq', out_signature='')
    def DisplayPasskey(self, dev, passkey, entered):
        code=f"{passkey:06d}"
        print('Typing passkey', code)
        type_code(code)

    @dbus.service.method('org.bluez.Agent1', in_signature='', out_signature='')
    def Release(self): pass

dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
bus=dbus.SystemBus()
path='/org/bluez/AutoKey'
agent=Agent(bus,path)
manager=dbus.Interface(bus.get_object('org.bluez','/org/bluez'),'org.bluez.AgentManager1')
manager.RegisterAgent(path,'KeyboardDisplay')
manager.RequestDefaultAgent(path)
print('bt_autokey running')
GLib.MainLoop().run()
PY
sudo chmod +x /usr/local/bin/bt_autokey.py

sudo tee /etc/systemd/system/bt-autokey.service >/dev/null <<'UNIT'
[Unit]
Description=Auto pass‑key typer for Classic‑HID pairing
After=bluetooth.target
Requires=bluetooth.target

[Service]
ExecStart=/usr/bin/env python3 /usr/local/bin/bt_autokey.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now bt-autokey.service

################################ 7  Bridge script #############################
# (unchanged; still at /usr/local/bin/bt_hid_bridge.py)

################################ 8  Service ###################################
VENVPY=/home/aollman/iControl/venv/bin/python3
sudo tee /etc/systemd/system/pi-bthid.service >/dev/null <<UNIT
[Unit]
Description=Pi Bluetooth HID Bridge (TCP→uinput)
After=bluetooth.target systemd-udev-settle.service
Requires=bluetooth.target

[Service]
ExecStartPre=/sbin/modprobe hidp
ExecStartPre=/sbin/modprobe uhid
ExecStart=${VENVPY} /usr/local/bin/bt_hid_bridge.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now pi-bthid.service

################################ Finish #######################################
printf '\n✔ Classic‑HID setup complete – rebooting in 5 s\n'; sleep 5; sudo reboot
