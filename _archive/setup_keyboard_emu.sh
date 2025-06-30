#!/bin/bash
#
# Copyright (c) 2024, Google LLC.
#
# This script automates the setup process for the Raspberry Pi 5
# Bluetooth HID Keyboard and Mouse Emulator.
#
# It performs the following actions:
# 1. Installs necessary system dependencies, including build tools.
# 2. Configures the BlueZ service to allow HID emulation.
# 3. Creates a Python virtual environment (venv).
# 4. Installs Python packages into the venv.
# 5. Creates the Python emulator script in the user's home directory.
#

# --- Script Configuration ---
PYTHON_SCRIPT_NAME="bt_hid_emu.py"
# Use the SUDO_USER variable to get the home directory of the user who ran sudo
# Fallback to /home/pi if SUDO_USER is not set
USER_HOME=$(getent passwd ${SUDO_USER:-pi} | cut -d: -f6)
VENV_PATH="${USER_HOME}/bt-hid-env"
PYTHON_SCRIPT_PATH="${USER_HOME}/iControl/${PYTHON_SCRIPT_NAME}"
BT_SERVICE_FILE="/lib/systemd/system/bluetooth.service"

# --- Safety Checks ---
# Exit immediately if a command exits with a non-zero status.
set -e

# Check if the script is being run with root privileges
if [ "$EUID" -ne 0 ]; then
  echo "Please run this script with sudo."
  exit 1
fi

echo "--- Starting Raspberry Pi 5 Bluetooth HID Combo Setup ---"

# --- Step 1: Update System and Install System Dependencies ---
echo "[1/6] Updating system and installing dependencies..."
apt-get update > /dev/null
# Add build dependencies for PyGObject and its dependency, pycairo
apt-get install -y python3-dbus python3-gi libbluetooth-dev python3-venv libcairo2-dev libgirepository1.0-dev pkg-config

echo "System dependencies installed successfully."

# --- Step 2: Configure the Bluetooth Service ---
echo "[2/6] Configuring Bluetooth service..."

# Check if the configuration is already done
if grep -q "noplugin=input" "$BT_SERVICE_FILE"; then
  echo "Bluetooth service already configured. Skipping."
else
  # Create a backup of the original service file
  cp "$BT_SERVICE_FILE" "${BT_SERVICE_FILE}.bak"
  echo "Backup of bluetooth.service created at ${BT_SERVICE_FILE}.bak"

  # Use sed to add the --noplugin=input flag
  sed -i '/^ExecStart=/s/$/ --noplugin=input/' "$BT_SERVICE_FILE"
  echo "Bluetooth service configured to allow HID emulation."
fi

# --- Step 3: Reload Systemd and Restart Bluetooth ---
echo "[3/6] Reloading systemd and restarting Bluetooth service..."
systemctl daemon-reload
systemctl restart bluetooth.service
echo "Bluetooth service restarted."

# --- Step 4: Create and Populate Virtual Environment ---
echo "[4/6] Creating Python virtual environment at ${VENV_PATH}..."
if [ -d "$VENV_PATH" ]; then
    echo "Virtual environment already exists. Skipping creation."
else
    # Create the venv as the regular user to ensure correct permissions
    sudo -u "${SUDO_USER:-pi}" python3 -m venv "${VENV_PATH}"
    echo "Virtual environment created."
fi

echo "Installing Python packages (PyGObject, dbus-python) into the venv..."
# Install packages using the venv's pip
# We need to run this as the user to avoid permission issues inside the venv
sudo -u "${SUDO_USER:-pi}" "${VENV_PATH}/bin/pip" install PyGObject dbus-python
echo "Python packages installed."

# --- Step 5: Create the Python Emulator Script ---
echo "[5/6] Creating Python emulator script at ${PYTHON_SCRIPT_PATH}..."

# Use a HEREDOC to write the Python script content
cat <<'EOF' > "${PYTHON_SCRIPT_PATH}"
#!/usr/bin/env python3
#
# Copyright (c) 2024, Google LLC.
#
# A simple Bluetooth HID keyboard and mouse emulator for Raspberry Pi 5.
# This script uses the modern BlueZ 5 D-Bus API.
#
# Based on examples from the community.
#

import os
import sys
import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
import time

# --- Configuration ---
DEVICE_NAME = "Pi5-HID-Combo"
SERVICE_NAME = "org.bluez"
AGENT_INTERFACE = SERVICE_NAME + '.Agent1'
AGENT_PATH = "/test/agent"
ADAPTER_INTERFACE = SERVICE_NAME + ".Adapter1"
DEVICE_INTERFACE = SERVICE_NAME + ".Device1"
PROFILE_MANAGER_INTERFACE = SERVICE_NAME + ".ProfileManager1"

# --- HID Profile Definition ---
HID_PROFILE_PATH = "/bluez/rpi/hid_profile"
SDP_UUID = "00001124-0000-1000-8000-00805f9b34fb"  # HID Profile
P_CTRL = 17  # Service Control Protocol
P_INTR = 19  # Service Interrupt Protocol

# --- HID Report Descriptor for a Combo Keyboard/Mouse Device ---
# This descriptor defines a combo device with two Report IDs:
# Report ID 1: Keyboard
# Report ID 2: Mouse
HID_REPORT_DESCRIPTOR = bytes([
    # Keyboard Collection
    0x05, 0x01,  # Usage Page (Generic Desktop)
    0x09, 0x06,  # Usage (Keyboard)
    0xA1, 0x01,  # Collection (Application)
    0x85, 0x01,  #   Report ID (1)
    0x05, 0x07,  #   Usage Page (Key Codes)
    0x19, 0xE0,  #   Usage Minimum (224)
    0x29, 0xE7,  #   Usage Maximum (231)
    0x15, 0x00,  #   Logical Minimum (0)
    0x25, 0x01,  #   Logical Maximum (1)
    0x75, 0x01,  #   Report Size (1)
    0x95, 0x08,  #   Report Count (8)
    0x81, 0x02,  #   Input (Data, Variable, Absolute) - Modifier Keys
    0x95, 0x01,  #   Report Count (1)
    0x75, 0x08,  #   Report Size (8)
    0x81, 0x01,  #   Input (Constant) - Reserved Byte
    0x95, 0x05,  #   Report Count (5)
    0x75, 0x01,  #   Report Size (1)
    0x05, 0x08,  #   Usage Page (LEDs)
    0x19, 0x01,  #   Usage Minimum (1)
    0x29, 0x05,  #   Usage Maximum (5)
    0x91, 0x02,  #   Output (Data, Variable, Absolute) - LEDs
    0x95, 0x01,  #   Report Count (1)
    0x75, 0x03,  #   Report Size (3)
    0x91, 0x01,  #   Output (Constant) - LED Padding
    0x95, 0x06,  #   Report Count (6)
    0x75, 0x08,  #   Report Size (8)
    0x15, 0x00,  #   Logical Minimum (0)
    0x25, 0x65,  #   Logical Maximum (101)
    0x05, 0x07,  #   Usage Page (Key Codes)
    0x19, 0x00,  #   Usage Minimum (0)
    0x29, 0x65,  #   Usage Maximum (101)
    0x81, 0x00,  #   Input (Data, Array) - Keypresses
    0xC0,        # End Collection (Application)

    # Mouse Collection
    0x05, 0x01,  # Usage Page (Generic Desktop)
    0x09, 0x02,  # Usage (Mouse)
    0xA1, 0x01,  # Collection (Application)
    0x85, 0x02,  #   Report ID (2)
    0x09, 0x01,  #   Usage (Pointer)
    0xA1, 0x00,  #   Collection (Physical)
    0x05, 0x09,  #     Usage Page (Buttons)
    0x19, 0x01,  #     Usage Minimum (1)
    0x29, 0x03,  #     Usage Maximum (3)
    0x15, 0x00,  #     Logical Minimum (0)
    0x25, 0x01,  #     Logical Maximum (1)
    0x95, 0x03,  #     Report Count (3)
    0x75, 0x01,  #     Report Size (1)
    0x81, 0x02,  #     Input (Data, Variable, Absolute) - Buttons
    0x95, 0x01,  #     Report Count (1)
    0x75, 0x05,  #     Report Size (5)
    0x81, 0x01,  #     Input (Constant) - Padding
    0x05, 0x01,  #     Usage Page (Generic Desktop)
    0x09, 0x30,  #     Usage (X)
    0x09, 0x31,  #     Usage (Y)
    0x15, 0x81,  #     Logical Minimum (-127)
    0x25, 0x7F,  #     Logical Maximum (127)
    0x75, 0x08,  #     Report Size (8)
    0x95, 0x02,  #     Report Count (2)
    0x81, 0x06,  #     Input (Data, Variable, Relative) - X, Y
    0xC0,        #   End Collection (Physical)
    0xC0,        # End Collection (Application)
])

# --- Keycode Mapping ---
KEYCODE = {
    'a': 0x04, 'b': 0x05, 'c': 0x06, 'd': 0x07, 'e': 0x08, 'f': 0x09,
    'g': 0x0A, 'h': 0x0B, 'i': 0x0C, 'j': 0x0D, 'k': 0x0E, 'l': 0x0F,
    'm': 0x10, 'n': 0x11, 'o': 0x12, 'p': 0x13, 'q': 0x14, 'r': 0x15,
    's': 0x16, 't': 0x17, 'u': 0x18, 'v': 0x19, 'w': 0x1A, 'x': 0x1B,
    'y': 0x1C, 'z': 0x1D,
    '1': 0x1E, '2': 0x1F, '3': 0x20, '4': 0x21, '5': 0x22, '6': 0x23,
    '7': 0x24, '8': 0x25, '9': 0x26, '0': 0x27,
    ' ': 0x2C,
    'A': 0x04, 'B': 0x05, 'C': 0x06, 'D': 0x07, 'E': 0x08, 'F': 0x09,
    'G': 0x0A, 'H': 0x0B, 'I': 0x0C, 'J': 0x0D, 'K': 0x0E, 'L': 0x0F,
    'M': 0x10, 'N': 0x11, 'O': 0x12, 'P': 0x13, 'Q': 0x14, 'R': 0x15,
    'S': 0x16, 'T': 0x17, 'U': 0x18, 'V': 0x19, 'W': 0x1A, 'X': 0x1B,
    'Y': 0x1C, 'Z': 0x1D,
}
MODIFIER = {
    'A': 0x02, 'B': 0x02, 'C': 0x02, 'D': 0x02, 'E': 0x02, 'F': 0x02,
    'G': 0x02, 'H': 0x02, 'I': 0x02, 'J': 0x02, 'K': 0x02, 'L': 0x02,
    'M': 0x02, 'N': 0x02, 'O': 0x02, 'P': 0x02, 'Q': 0x02, 'R': 0x02,
    'S': 0x02, 'T': 0x02, 'U': 0x02, 'V': 0x02, 'W': 0x02, 'X': 0x02,
    'Y': 0x02, 'Z': 0x02,
}


class HIDProfile(dbus.service.Object):
    def __init__(self, bus, path):
        super().__init__(bus, path)
    
    @dbus.service.method(PROFILE_MANAGER_INTERFACE, in_signature="", out_signature="")
    def Release(self):
        print("Profile released")

    @dbus.service.method(PROFILE_MANAGER_INTERFACE, in_signature="o", out_signature="")
    def NewConnection(self, device_path):
        print(f"New connection from {device_path}")
        HIDDevice(bus, device_path)

    @dbus.service.method(PROFILE_MANAGER_INTERFACE, in_signature="o", out_signature="")
    def RequestDisconnection(self, device_path):
        print(f"Requesting disconnection from {device_path}")


class HIDDevice(dbus.service.Object):
    def __init__(self, bus, path):
        super().__init__(bus, path)
        self.bus = bus
        self.path = path
        self.ctrl_sock = None
        self.intr_sock = None
        self.device = dbus.Interface(self.bus.get_object(SERVICE_NAME, path), DEVICE_INTERFACE)
        self.device.connect_to_signal("PropertyChanged", self.property_changed_cb)
        self.connect()

    def connect(self):
        try:
            self.ctrl_sock = self.device.connect_l2cap(P_CTRL)
            self.intr_sock = self.device.connect_l2cap(P_INTR)
            print("Sockets connected successfully.")
            GLib.timeout_add_seconds(2, self.send_test_events)
        except dbus.exceptions.DBusException as e:
            print(f"Error connecting sockets: {e}")
            self.disconnect()

    def disconnect(self):
        if self.ctrl_sock: self.ctrl_sock.close()
        if self.intr_sock: self.intr_sock.close()
        print("Sockets disconnected.")

    def property_changed_cb(self, interface, changed, invalidated):
        if 'Connected' in changed and not changed['Connected']:
            self.disconnect()

    def send_hid_report(self, report):
        if not self.intr_sock:
            print("Cannot send report: Interrupt socket not connected.")
            return
        try:
            self.intr_sock.send(bytes(report))
        except Exception as e:
            print(f"Error sending report: {e}")
            self.disconnect()

    # --- Keyboard Methods ---
    def send_keypress(self, modifier, key):
        # Report ID 1 for keyboard
        report = [0xA1, 0x01, modifier, 0, key, 0, 0, 0, 0, 0]
        self.send_hid_report(report)
        # Release
        report = [0xA1, 0x01, 0, 0, 0, 0, 0, 0, 0, 0]
        self.send_hid_report(report)

    def send_string(self, message):
        print(f"Typing: {message}")
        for char in message:
            mod = MODIFIER.get(char, 0)
            key_code = KEYCODE.get(char)
            if key_code:
                self.send_keypress(mod, key_code)
                time.sleep(0.05)

    # --- Mouse Methods ---
    def send_mouse_report(self, buttons, dx, dy):
        def to_signed_byte(n):
            # Convert integer to signed 8-bit value
            return n if n >= 0 else n + 256
        # Report ID 2 for mouse
        report = [0xA1, 0x02, buttons, to_signed_byte(dx), to_signed_byte(dy)]
        self.send_hid_report(report)

    def click_mouse(self, button=0x01): # Default to left click (0x01)
        self.send_mouse_report(button, 0, 0) # Press
        self.send_mouse_report(0, 0, 0)      # Release

    def move_mouse(self, dx, dy):
        self.send_mouse_report(0, dx, dy)

    # --- Test Function ---
    def send_test_events(self):
        print("--- Sending test events ---")
        self.send_string("Hello! I am a keyboard and mouse.")
        time.sleep(1)
        
        print("Moving mouse in a square and clicking...")
        for _ in range(2):
            self.move_mouse(50, 0); time.sleep(0.2)
            self.move_mouse(0, 50); time.sleep(0.2)
            self.move_mouse(-50, 0); time.sleep(0.2)
            self.move_mouse(0, -50); time.sleep(0.2)
        
        self.click_mouse() # Left click
        print("--- Test complete ---")
        return False # Stop timer from repeating


if __name__ == "__main__":
    if os.geteuid() != 0:
        sys.exit("This script must be run as root")

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    mainloop = GLib.MainLoop()

    # Register the HID profile
    profile_manager = dbus.Interface(bus.get_object(SERVICE_NAME, "/org/bluez"), PROFILE_MANAGER_INTERFACE)
    
    profile_opts = {
        "ServiceRecord": "",
        "Role": "server",
        "RequireAuthentication": False, # Set to False for easier testing
        "RequireAuthorization": False,  # Set to False for easier testing
        "AutoConnect": True,
        "Name": DEVICE_NAME,
        "Description": "Raspberry Pi HID Combo",
        "Provider": "Raspberry Pi Foundation",
        "Descriptor": dbus.ByteArray(HID_REPORT_DESCRIPTOR),
    }

    try:
        profile_manager.RegisterProfile(HID_PROFILE_PATH, SDP_UUID, profile_opts)
        print("HID Combo Profile registered successfully.")
    except Exception as e:
        print(f"Error registering profile: {e}")
        sys.exit(1)

    # Make discoverable
    adapter_path = bus.get_object(SERVICE_NAME, "/org/bluez/hci0").Get(ADAPTER_INTERFACE, "Address", dbus_interface=dbus.PROPERTIES_IFACE)
    adapter = dbus.Interface(bus.get_object(SERVICE_NAME, f"/org/bluez/{adapter_path.replace(':', '_')}"), ADAPTER_INTERFACE)
    adapter.set("Discoverable", dbus.Boolean(True))
    adapter.set("Alias", dbus.String(DEVICE_NAME))

    print(f"Device '{DEVICE_NAME}' is now discoverable.")
    print("Waiting for connections...")

    try:
        mainloop.run()
    except KeyboardInterrupt:
        print("\nShutting down...")
        profile_manager.UnregisterProfile(HID_PROFILE_PATH)
        mainloop.quit()
EOF

# --- Step 6: Set Permissions ---
echo "[6/6] Setting ownership and permissions for the Python script..."
# Set the owner to be the user who ran sudo
chown "${SUDO_USER:-pi}:${SUDO_USER:-pi}" "${PYTHON_SCRIPT_PATH}"
# Make the script executable
chmod +x "${PYTHON_SCRIPT_PATH}"

echo ""
echo "--- Setup Complete! ---"
echo ""
echo "The emulator script has been created at:"
echo "  ${PYTHON_SCRIPT_PATH}"
echo ""
echo "The Python virtual environment is at:"
echo "  ${VENV_PATH}"
echo ""
echo "To start the keyboard and mouse emulator, run the following command:"
echo "  sudo ${VENV_PATH}/bin/python ${PYTHON_SCRIPT_PATH}"
echo ""
