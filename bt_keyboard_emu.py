#!/usr/bin/env python3
#
# Copyright (c) 2024, Google LLC.
#
# A simple Bluetooth HID keyboard emulator for Raspberry Pi 5.
# This script uses the modern BlueZ 5 D-Bus API.
#
# Based on examples from the community, especially the work of
# a-sync and other open-source contributors.
#

import os
import sys
import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
import time

# --- Configuration ---
DEVICE_NAME = "Pi5-Keyboard"
SERVICE_NAME = "org.bluez"
AGENT_INTERFACE = SERVICE_NAME + '.Agent1'
AGENT_PATH = "/test/agent"
ADAPTER_INTERFACE = SERVICE_NAME + ".Adapter1"
DEVICE_INTERFACE = SERVICE_NAME + ".Device1"
PROFILE_MANAGER_INTERFACE = SERVICE_NAME + ".ProfileManager1"

# --- HID Profile Definition ---
# This defines the Raspberry Pi as a Human Interface Device (HID)
# and specifies its capabilities, primarily as a keyboard.
HID_PROFILE_PATH = "/bluez/rpi/hid_profile"
# Service-level UUIDs
SDP_UUID = "00001124-0000-1000-8000-00805f9b34fb"  # HID Profile
# Profile-level UUIDs
P_CTRL = 17  # Service Control Protocol
P_INTR = 19  # Service Interrupt Protocol

# --- HID Report Descriptor ---
# This is a crucial part of the HID specification. It describes the
# data format for the keyboard, including which bits correspond to
# which keys and modifiers (like Shift, Ctrl, etc.).
# This descriptor defines a standard 104-key keyboard.
HID_REPORT_DESCRIPTOR = bytes([
    0x05, 0x01,  # Usage Page (Generic Desktop)
    0x09, 0x06,  # Usage (Keyboard)
    0xA1, 0x01,  # Collection (Application)
    # Modifier Keys
    0x05, 0x07,  # Usage Page (Key Codes)
    0x19, 0xE0,  # Usage Minimum (224)
    0x29, 0xE7,  # Usage Maximum (231)
    0x15, 0x00,  # Logical Minimum (0)
    0x25, 0x01,  # Logical Maximum (1)
    0x75, 0x01,  # Report Size (1)
    0x95, 0x08,  # Report Count (8)
    0x81, 0x02,  # Input (Data, Variable, Absolute)
    # Reserved Byte
    0x95, 0x01,  # Report Count (1)
    0x75, 0x08,  # Report Size (8)
    0x81, 0x01,  # Input (Constant)
    # LEDs
    0x95, 0x05,  # Report Count (5)
    0x75, 0x01,  # Report Size (1)
    0x05, 0x08,  # Usage Page (LEDs)
    0x19, 0x01,  # Usage Minimum (1)
    0x29, 0x05,  # Usage Maximum (5)
    0x91, 0x02,  # Output (Data, Variable, Absolute)
    # Reserved
    0x95, 0x01,  # Report Count (1)
    0x75, 0x03,  # Report Size (3)
    0x91, 0x01,  # Output (Constant)
    # Keypresses
    0x95, 0x06,  # Report Count (6)
    0x75, 0x08,  # Report Size (8)
    0x15, 0x00,  # Logical Minimum (0)
    0x25, 0x65,  # Logical Maximum (101)
    0x05, 0x07,  # Usage Page (Key Codes)
    0x19, 0x00,  # Usage Minimum (0)
    0x29, 0x65,  # Usage Maximum (101)
    0x81, 0x00,  # Input (Data, Array)
    0xC0,        # End Collection
])

# --- Keycode Mapping ---
# Maps ASCII characters to HID keycodes.
# This is a simplified map and doesn't cover all keys or special chars.
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
    """
    Manages the Bluetooth HID profile registration.
    This class advertises the HID service to the system.
    """
    def __init__(self, bus, path):
        super().__init__(bus, path)
        self.fd = -1
        self.path = path

    def get_profile_descriptor(self):
        """Returns the HID profile descriptor."""
        profile = dbus.Dictionary({
            "ServiceRecord": self.get_service_record(),
            "Role": "server",
            "RequireAuthentication": True,
            "RequireAuthorization": True
        })
        return profile

    def get_service_record(self):
        """Returns the Service Discovery Protocol (SDP) record."""
        record = dbus.String(
            f"""
            <?xml version="1.0" encoding="UTF-8" ?>
            <record>
              <attribute id="0x0001">
                <uint16 value="0x1124" />
              </attribute>
              <attribute id="0x0004">
                <sequence>
                  <sequence>
                    <uuid value="0x0100" />
                    <uint16 value="0x0011" />
                  </sequence>
                  <sequence>
                    <uuid value="0x0011" />
                  </sequence>
                </sequence>
              </attribute>
              <attribute id="0x0100">
                <text value="{DEVICE_NAME}" name="name" />
              </attribute>
              <attribute id="0x0200">
                <uint16 value="0x0111" />
              </attribute>
              <attribute id="0x0201">
                <uint16 value="0x0100" />
              </attribute>
              <attribute id="0x0202">
                <uint8 value="0x40" />
              </attribute>
              <attribute id="0x0204">
                <boolean value="true" />
              </attribute>
              <attribute id="0x0205">
                <boolean value="true" />
              </attribute>
              <attribute id="0x0206">
                <sequence>
                    <uint16 value="0x0040" />
                    <uint16 value="0x0900" />
                </sequence>
              </attribute>
              <attribute id="0x0207">
                <uint16 value="0x0400" />
              </attribute>
            </record>
            """
        )
        return record

    @dbus.service.method(PROFILE_MANAGER_INTERFACE,
                         in_signature="o",
                         out_signature="")
    def NewConnection(self, device_path):
        """
        Called by BlueZ when a new device connects to this profile.
        """
        print(f"New connection from {device_path}")
        self.conn_device_path = device_path
        # Create a HIDDevice instance to handle the connection
        HIDDevice(bus, device_path)

    @dbus.service.method(PROFILE_MANAGER_INTERFACE,
                         in_signature="o",
                         out_signature="")
    def RequestDisconnection(self, device_path):
        """
        Called by BlueZ when a device requests disconnection.
        """
        print(f"Requesting disconnection from {device_path}")

    @dbus.service.method(PROFILE_MANAGER_INTERFACE,
                         in_signature="",
                         out_signature="")
    def Release(self):
        """
        Called when the profile is unregistered.
        """
        print("Profile released")


class HIDDevice(dbus.service.Object):
    """
    Represents the emulated HID device and handles sending reports.
    """
    def __init__(self, bus, path):
        super().__init__(bus, path)
        self.bus = bus
        self.path = path
        self.ctrl_sock = None
        self.intr_sock = None
        self.device = dbus.Interface(self.bus.get_object(SERVICE_NAME, path), DEVICE_INTERFACE)
        self.device.connect_to_signal("PropertyChanged", self.property_changed)

        self.connect()

    def connect(self):
        """Establishes the L2CAP sockets for control and interrupt channels."""
        try:
            self.ctrl_sock = self.device.connect_l2cap(P_CTRL)
            self.intr_sock = self.device.connect_l2cap(P_INTR)
            print("Sockets connected successfully.")
            # Start a timer to send a test message
            GLib.timeout_add_seconds(2, self.send_test_message)
        except dbus.exceptions.DBusException as e:
            print(f"Error connecting sockets: {e}")
            self.disconnect()

    def disconnect(self):
        """Closes the L2CAP sockets."""
        if self.ctrl_sock:
            self.ctrl_sock.close()
            self.ctrl_sock = None
        if self.intr_sock:
            self.intr_sock.close()
            self.intr_sock = None
        print("Sockets disconnected.")

    def property_changed(self, interface, changed, invalidated):
        """Handles property changes, like disconnection."""
        if 'Connected' in changed and not changed['Connected']:
            print("Device disconnected.")
            self.disconnect()

    def send_hid_report(self, report):
        """Sends a HID report to the host via the interrupt channel."""
        if self.intr_sock:
            try:
                self.intr_sock.send(bytes(report))
            except Exception as e:
                print(f"Error sending report: {e}")
                self.disconnect()
        else:
            print("Cannot send report: Interrupt socket is not connected.")

    def send_keypress(self, modifier, key):
        """Sends a key press and release event."""
        # Key Press
        report = [0xA1, 0x01, modifier, 0x00, key, 0x00, 0x00, 0x00, 0x00, 0x00]
        self.send_hid_report(report)
        # Key Release
        report = [0xA1, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
        self.send_hid_report(report)

    def send_string(self, message):
        """Types out a string of characters."""
        print(f"Typing: {message}")
        for char in message:
            mod = MODIFIER.get(char, 0x00)
            key_code = KEYCODE.get(char)
            if key_code:
                self.send_keypress(mod, key_code)
                time.sleep(0.05) # Small delay between keystrokes

    def send_test_message(self):
        """Sends a 'Hello World' message as a test."""
        self.send_string("Hello from Pi 5!")
        return False # This stops the timer from repeating


if __name__ == "__main__":
    if os.geteuid() != 0:
        sys.exit("This script must be run as root (sudo)")

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    mainloop = GLib.MainLoop()

    # Get the Bluetooth adapter
    adapter_path = bus.get_object(SERVICE_NAME, "/org/bluez/hci0").Get(
        ADAPTER_INTERFACE, "Address", dbus_interface=dbus.PROPERTIES_IFACE
    )
    adapter = dbus.Interface(
        bus.get_object(SERVICE_NAME, f"/org/bluez/{adapter_path.replace(':', '_')}"),
        ADAPTER_INTERFACE
    )

    # Register the HID profile
    profile_manager = dbus.Interface(
        bus.get_object(SERVICE_NAME, "/org/bluez"),
        PROFILE_MANAGER_INTERFACE
    )
    profile = HIDProfile(bus, HID_PROFILE_PATH)
    profile_opts = profile.get_profile_descriptor()

    try:
        profile_manager.RegisterProfile(HID_PROFILE_PATH, SDP_UUID, profile_opts)
        print("HID Profile registered successfully.")
    except dbus.exceptions.DBusException as e:
        print(f"Error registering profile: {e}")
        sys.exit(1)

    # Make the Raspberry Pi discoverable
    adapter.set("Discoverable", dbus.Boolean(True))
    print(f"Device '{DEVICE_NAME}' is now discoverable.")
    print("Waiting for connections...")

    try:
        mainloop.run()
    except KeyboardInterrupt:
        print("\nShutting down...")
        profile_manager.UnregisterProfile(HID_PROFILE_PATH)
        mainloop.quit()
