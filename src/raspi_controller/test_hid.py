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
        print(f"Moved by ({dx}, {dy}). New estimated relative position: ({self.x}, {self.y})", end='\r')

    async def move_to_absolute(self, x: int, y: int):
        """Moves to an absolute screen position."""
        print(f"\nMoving to absolute position ({x}, {y})...")
        # 1. Reset cursor to top-left (0,0) by moving a large negative distance
        await self._send_command("m:-32767,-32767")
        await asyncio.sleep(0.05)
        # 2. Move to the absolute target coordinates
        await self._send_command(f"m:{x},{y}")
        # Reset our internal relative tracker
        self.x = x
        self.y = y
        print(f"Moved to ({x}, {y}). Use WASD for relative moves from here.")

async def main():
    controller = HIDTestController()

    if not await controller.connect():
        return

    print("Press 'p' to set an absolute position.")

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
        elif key == 'p':
            try:
                # Prompt for coordinates
                coord_str = input("\nEnter coordinates (x,y): ")
                x_str, y_str = coord_str.strip().split(',')
                x = int(x_str)
                y = int(y_str)
                await controller.move_to_absolute(x, y)
            except (ValueError, IndexError):
                print("\nInvalid format. Please use x,y (e.g., 280,550)")
        elif key == 'q':
            break
    
    await controller.disconnect()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting.") 