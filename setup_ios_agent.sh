#!/usr/bin/env bash
# Pi‑5 **BLE‑HID (mouse+basic keys) bridge** for iOS – vB1  (2025‑06‑19)
# - Advertises BLE “Generic Mouse” with HID over GATT (HOGP).
# - Creates a userspace UHID device so BlueZ exposes the HID service.
# - GPT actions are sent over TCP → /dev/uinput (same bridge as before).
#   iPhone pairs with **NO PIN**.
set -euo pipefail
sudo -v

VENVPY=/home/aollman/iControl/venv/bin/python3

################################ 1  Packages #################################
sudo apt update
sudo apt install -y \
  python3-venv python3-pip python3-evdev build-essential libudev-dev \
  bluez bluez-tools libbluetooth-dev git \
  python3-dbus python3-gi python3-gi-cairo gir1.2-glib-2.0

################################ 2  BlueZ BLE‑only config ####################
CFG=/etc/bluetooth/main.conf
patch(){ grep -qE "^[#[:space:]]*$1" "$CFG" && \
         sudo sed -i "s|^[#[:space:]]*$1.*|$1 = $2|" "$CFG" || \
         echo "$1 = $2" | sudo tee -a "$CFG" >/dev/null; }
patch Name Pi-HID
patch Class 0x002580           # Peripheral | Mouse only (for appearance)
patch ControllerMode dual      # enable BR/EDR + LE (HID over GATT)
patch DiscoverableTimeout 0

sudo sed -i 's|^ExecStart=.*|ExecStart=/usr/libexec/bluetooth/bluetoothd --experimental --noplugin=sap -P battery,hog|' \
  /lib/systemd/system/bluetooth.service

################################ 2.1 Kernel uhid ################################
sudo modprobe uhid
grep -qxF "uhid" /etc/modules || echo "uhid" | sudo tee -a /etc/modules >/dev/null
sudo systemctl daemon-reload
sudo rfkill unblock bluetooth
sudo systemctl restart bluetooth

################################ 3  Python venv (for uhid lib) ################
mkdir -p ~/iControl
python3 -m venv ~/iControl/venv
source ~/iControl/venv/bin/activate
pip install -q --upgrade pip
pip install -q evdev uhid

deactivate

################################ 4  UHID mouse device ########################
# Report‑descriptor: 3‑button mouse with X/Y rel
sudo tee /usr/local/bin/uhid_mouse.py >/dev/null <<'PY'
#!/usr/bin/env python3
import uhid, time
RD = bytes([
 0x05,0x01,0x09,0x02,0xA1,0x01,0x09,0x01,0xA1,0x00,
 0x05,0x09,0x19,0x01,0x29,0x03,0x15,0x00,0x25,0x01,
 0x95,0x03,0x75,0x01,0x81,0x02,0x95,0x01,0x75,0x05,0x81,0x03,
 0x05,0x01,0x09,0x30,0x09,0x31,0x15,0x81,0x25,0x7F,
 0x75,0x08,0x95,0x02,0x81,0x06,0xC0,0xC0])

# name, vendor_id, product_id, version, country, report_desc
# name, vendor_id, product_id, report_desc (python‑uhid on Bookworm expects 4 args)
# python-uhid (Bookworm) signature: UHIDDevice(name, report_descriptor)
dev = uhid.UHIDDevice('Pi-HID', RD)
print('UHID mouse created'); dev.create();
try:
    while True: time.sleep(3600)
except KeyboardInterrupt:
    dev.destroy()
PY
sudo chmod +x /usr/local/bin/uhid_mouse.py

sudo tee /etc/systemd/system/uhid-mouse.service >/dev/null <<UNIT
[Unit]
Description=User-space UHID Mouse (BLE-HID backend)
After=systemd-udev-settle.service

[Service]
ExecStart=${VENVPY} /usr/local/bin/uhid_mouse.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
UNIT

# enable after venv ready
sudo systemctl enable --now uhid-mouse.service

################################ 4  bt_init.sh – BLE advertise ###############
sudo tee /usr/local/sbin/bt_init.sh >/dev/null <<'SH'
#!/bin/bash
set -e
for _ in {1..10}; do hciconfig hci0 >/dev/null 2>&1 && break; sleep 1; done
bluetoothctl <<EOF
power on
pairable on
discoverable on
agent NoInputNoOutput
default-agent
menu advertise
appearance 962                              # Generic Mouse appearance
uuids 00001812-0000-1000-8000-00805f9b34fb   # HID Service UUID
back
advertise on
system-alias Pi-HID
quit
EOF
SH
sudo chmod +x /usr/local/sbin/bt_init.sh

sudo tee /etc/systemd/system/bt-agent.service >/dev/null <<'UNIT'
[Unit]
Description=Init BlueZ BLE HID advertising (NoInputNoOutput)
After=bluetooth.target uhid-mouse.service
Requires=bluetooth.target uhid-mouse.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/bt_init.sh

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now bt-agent.service

################################ 5  uinput / uhid perms ######################
# make both character devices world‑writable so non‑root bridge can open them
cat <<'RULES' | sudo tee /etc/udev/rules.d/99-hid-perms.rules
KERNEL=="uinput", MODE="0666"
KERNEL=="uhid",   MODE="0666"
RULES
sudo udevadm control --reload-rules
sudo modprobe uinput uhid
sudo udevadm trigger /dev/uinput /dev/uhid || true
echo 'KERNEL=="uinput", MODE="0666"' | sudo tee /etc/udev/rules.d/99-uinput.rules
sudo modprobe uinput
sudo udevadm trigger /dev/uinput || true



################################ 7  Bridge script (unchanged) #################
# Assumes /usr/local/bin/bt_hid_bridge.py already present from previous runs.

################################ 8  Service ###################################
VENVPY=/home/aollman/iControl/venv/bin/python3
sudo tee /etc/systemd/system/pi-bthid.service >/dev/null <<UNIT
[Unit]
Description=Pi BLE HID Bridge (TCP→uinput)
After=bluetooth.target systemd-udev-settle.service bt-agent.service
Requires=bluetooth.target bt-agent.service

[Service]
ExecStartPre=/sbin/modprobe uhid
ExecStart=${VENVPY} /usr/local/bin/bt_hid_bridge.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable --now pi-bthid.service

################################ Finish #######################################
printf '\n✔ BLE‑HID setup complete – rebooting in 5 s\n'; sleep 5; sudo reboot
