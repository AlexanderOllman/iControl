#!/bin/bash
# setup_ios_agent_pi5.sh
# One-shot bootstrap for the all-in-one Pi-5 iPhone agent
set -euo pipefail
sudo -v    # ask for sudo password up-front

echo "========== 1. Updating and installing base packages =========="
sudo apt update
sudo apt install -y \
  python3-pip python3-venv python3-opencv python3-dev \
  git curl unzip \
  libatlas-base-dev libjpeg-dev libtiff5 libopenjp2-7 \
  libavcodec-dev libavformat-dev libswscale-dev libv4l-dev \
  libxvidcore-dev libx264-dev libhidapi-dev

echo "========== 2. Enabling dwc2 (USB gadget) =========="
CFG=/boot/config.txt
CMD=/boot/cmdline.txt
grep -q '^dtoverlay=dwc2' $CFG || echo 'dtoverlay=dwc2' | sudo tee -a $CFG
sudo sed -i 's/\(root=\S\+\s\+\)/\1modules-load=dwc2 /' $CMD

echo "========== 3. Preparing gadget filesystem =========="
sudo modprobe libcomposite
sudo mount -t configfs none /sys/kernel/config || true

echo "========== 4. Installing iphone_hid_gadget.sh =========="
sudo tee /usr/bin/iphone_hid_gadget.sh >/dev/null <<'EOF'
#!/bin/bash
set -e
G=/sys/kernel/config/usb_gadget/iphone
UDC=$(ls /sys/class/udc | head -n1)

# clean any previous gadget
if [ -d "$G" ]; then
  echo "" > "$G/UDC" 2>/dev/null || true
  find "$G" -type l -exec rm -f {} +
  find "$G" -depth -type d -exec rmdir {} + 2>/dev/null || true
fi

mkdir -p "$G"; cd "$G"
echo 0x1d6b > idVendor     # Linux Foundation
echo 0x0104 > idProduct    # Multifunction Composite
echo 0x0100 > bcdDevice
echo 0x0200 > bcdUSB

mkdir -p strings/0x409
echo "0001"               > strings/0x409/serialnumber
echo "Pi 5 Agent"         > strings/0x409/manufacturer
echo "Pi 5 to iPhone"     > strings/0x409/product

######## Keyboard (hid.usb0) ########
mkdir -p functions/hid.usb0
echo 1  > functions/hid.usb0/protocol
echo 8  > functions/hid.usb0/report_length
cat > functions/hid.usb0/report_desc <<'KBD'
05 01 09 06 A1 01 05 07 19 E0 29 E7 15 00 25 01
75 01 95 08 81 02 95 01 75 08 81 03 95 05 75 01
05 08 19 01 29 05 91 02 95 01 75 03 91 03 95 06
75 08 15 00 25 65 05 07 19 00 29 65 81 00 C0
KBD

######## Absolute touch (hid.usb1) ########
mkdir -p functions/hid.usb1
echo 2   > functions/hid.usb1/protocol
echo 16  > functions/hid.usb1/report_length
cat > functions/hid.usb1/report_desc <<'TOUCH'
05 0D 09 04 A1 01 09 22 A1 00 05 01 09 30 09 31
15 00 26 FF 7F 75 10 95 02 81 02 C0 C0
TOUCH

######## Configuration ########
mkdir -p configs/c.1
echo 120 > configs/c.1/MaxPower
ln -s functions/hid.usb0 configs/c.1/
ln -s functions/hid.usb1 configs/c.1/

echo "$UDC" > UDC
echo "✓ iPhone HID gadget is live (keyboard + touch)"
EOF
sudo chmod +x /usr/bin/iphone_hid_gadget.sh

echo "—— Adding gadget script to /etc/rc.local ——"
sudo sed -i '/^exit 0/i /usr/bin/iphone_hid_gadget.sh' /etc/rc.local

echo "========== 5. Python venv + packages =========="
mkdir -p ~/iControl
python3 -m venv ~/iControl/venv
source ~/iControl/venv/bin/activate
pip install --upgrade pip
pip install openai python-dotenv opencv-python

echo "========== 6. Done. Rebooting in 5 seconds =========="
sleep 5
sudo reboot
