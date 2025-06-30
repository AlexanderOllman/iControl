import asyncio
from bleak import BleakClient, BleakScanner

# Configuration for the ESP32-C6 BLE server
DEVICE_NAME = "iControl HID"
SERVICE_UUID = "c48e6067-5295-48d3-8d5c-0395f61792b1"
CHARACTERISTIC_UUID = "c48e6068-5295-48d3-8d5c-0395f61792b1"

class HIDController:
    """A class to manage the BLE connection and send HID commands."""

    def __init__(self):
        self.client: BleakClient = None

    async def connect(self):
        """Scans for the device and connects to it."""
        print(f"Scanning for '{DEVICE_NAME}'...")
        device = await BleakScanner.find_device_by_name(DEVICE_NAME)
        if device is None:
            print(f"Could not find device with name '{DEVICE_NAME}'")
            return

        print(f"Connecting to {device.name} ({device.address})...")
        self.client = BleakClient(device)
        try:
            await self.client.connect()
            print("Connected!")
        except Exception as e:
            print(f"Failed to connect: {e}")
            self.client = None

    async def disconnect(self):
        """Disconnects from the BLE device."""
        if self.client and self.client.is_connected:
            await self.client.disconnect()
            print("Disconnected.")
        self.client = None

    async def _send_command(self, command: str):
        """Sends a command string to the ESP32-C6."""
        if not self.client or not self.client.is_connected:
            print("Not connected. Please connect first.")
            return

        try:
            await self.client.write_gatt_char(CHARACTERISTIC_UUID, bytearray(command, 'utf-8'))
        except Exception as e:
            print(f"Failed to send command: {e}")

    async def type_string(self, text: str):
        """Sends a command to type a string."""
        await self._send_command(f"k:{text}")

    async def move_mouse(self, x: int, y: int):
        """Sends a command to move the mouse."""
        await self._send_command(f"m:{x},{y}")

    async def mouse_click(self, button: str):
        """Sends a command to click a mouse button ('left', 'right', 'middle')."""
        await self._send_command(f"mc:{button}")
    
    async def mouse_press(self, button: str):
        """Sends a command to press a mouse button ('left', 'right', 'middle')."""
        await self._send_command(f"mp:{button}")

    async def mouse_release(self, button: str):
        """Sends a command to release a mouse button ('left', 'right', 'middle')."""
        await self._send_command(f"mr:{button}")


async def main():
    """Main function to demonstrate the HIDController."""
    controller = HIDController()
    
    try:
        await controller.connect()

        if controller.client and controller.client.is_connected:
            print("\n--- Sending test commands ---")
            
            # Example 1: Type some text
            print("Typing 'Hello from the Raspberry Pi!'")
            await controller.type_string("Hello from the Raspberry Pi!")
            await asyncio.sleep(2)

            # Example 2: Move the mouse in a square
            print("Moving mouse in a square...")
            await controller.move_mouse(50, 0)
            await asyncio.sleep(1)
            await controller.move_mouse(0, 50)
            await asyncio.sleep(1)
            await controller.move_mouse(-50, 0)
            await asyncio.sleep(1)
            await controller.move_mouse(0, -50)
            await asyncio.sleep(1)

            # Example 3: Left mouse click
            print("Performing a left mouse click.")
            await controller.mouse_click("left")
            await asyncio.sleep(2)

            print("--- Test commands finished ---")

    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        await controller.disconnect()


if __name__ == "__main__":
    # To run this script, you will need to install the bleak library:
    # pip install bleak
    
    # You may also need to run as root or grant permissions on Linux:
    # sudo python main.py
    
    asyncio.run(main()) 