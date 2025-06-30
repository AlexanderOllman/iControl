import asyncio
from bleak import BleakClient, BleakScanner
import readchar

# --- Configuration ---
DEVICE_NAME = "iControl HID"
CHARACTERISTIC_UUID = "c48e6068-5295-48d3-8d5c-0395f61792b1"
MOVE_STEP = 50

class HIDTestController:
    """A minimal controller for testing BLE HID mouse movements."""

    def __init__(self):
        self.client: BleakClient = None
        self.x = 0
        self.y = 0

    async def connect(self):
        print(f"Scanning for '{DEVICE_NAME}'...")
        device = await BleakScanner.find_device_by_name(DEVICE_NAME)
        if not device:
            print("Device not found.")
            return False
        
        self.client = BleakClient(device)
        await self.client.connect()
        print("Connected! Use WASD to move, Q to quit.")
        return True

    async def disconnect(self):
        if self.client:
            await self.client.disconnect()
        print("\nDisconnected.")

    async def _send_command(self, command: str):
        if not self.client:
            return
        await self.client.write_gatt_char(CHARACTERISTIC_UUID, bytearray(command, 'utf-8'), response=False)

    async def move_relative(self, dx: int, dy: int):
        """Sends a relative move command."""
        self.x += dx
        self.y += dy
        await self._send_command(f"m:{dx},{dy}")
        print(f"Moved by ({dx}, {dy}). New estimated position: ({self.x}, {self.y})", end='\r')

async def main():
    controller = HIDTestController()

    if not await controller.connect():
        return

    while True:
        key = readchar.readkey()
        
        if key == 'w':
            await controller.move_relative(0, -MOVE_STEP)
        elif key == 's':
            await controller.move_relative(0, MOVE_STEP)
        elif key == 'a':
            await controller.move_relative(-MOVE_STEP, 0)
        elif key == 'd':
            await controller.move_relative(MOVE_STEP, 0)
        elif key == 'q':
            break
    
    await controller.disconnect()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting.") 