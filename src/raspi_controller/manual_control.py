import asyncio
from pynput import keyboard
from main import HIDController  # Reuse the HIDController from our main script

# --- Configuration ---
MOVE_STEP = 25  # Pixels to move with each key press

class ManualController:
    def __init__(self, hid_controller):
        self.hid = hid_controller
        self.x = 0
        self.y = 0
        self.running = True

    def on_press(self, key):
        """Callback function for keyboard key presses."""
        try:
            if key == keyboard.Key.up:
                self.y -= MOVE_STEP
                asyncio.run_coroutine_threadsafe(self.hid.move_mouse_relative(0, -MOVE_STEP), asyncio.get_event_loop())
            elif key == keyboard.Key.down:
                self.y += MOVE_STEP
                asyncio.run_coroutine_threadsafe(self.hid.move_mouse_relative(0, MOVE_STEP), asyncio.get_event_loop())
            elif key == keyboard.Key.left:
                self.x -= MOVE_STEP
                asyncio.run_coroutine_threadsafe(self.hid.move_mouse_relative(-MOVE_STEP, 0), asyncio.get_event_loop())
            elif key == keyboard.Key.right:
                self.x += MOVE_STEP
                asyncio.run_coroutine_threadsafe(self.hid.move_mouse_relative(MOVE_STEP, 0), asyncio.get_event_loop())
            elif key == keyboard.Key.space:
                # Reset to our script's logical origin
                self.x = 0
                self.y = 0
                asyncio.run_coroutine_threadsafe(self.hid.click_at_position(0, 0, click=False), asyncio.get_event_loop())
            
            # Print current coordinates after every move
            print(f"Coordinates: (x={self.x}, y={self.y})", end='\r')

        except AttributeError:
            # Handle regular key presses if needed
            pass

    def on_release(self, key):
        """Callback function for keyboard key releases."""
        if key == keyboard.Key.esc:
            # Stop listener
            self.running = False
            return False

async def main():
    """Main execution loop for manual control."""
    hid = HIDController()

    print("Connecting to HID device...")
    if not await hid.connect():
        return

    controller = ManualController(hid)
    listener = keyboard.Listener(on_press=controller.on_press, on_release=controller.on_release)
    
    print("\n" + "="*40)
    print("Manual Control Enabled")
    print(" - Use arrow keys to move the cursor.")
    print(" - Use SPACE to reset to origin (0,0).")
    print(" - Press ESC to quit.")
    print("="*40)
    
    listener.start()
    
    # Keep the script running while the listener is active
    while controller.running:
        await asyncio.sleep(0.1)

    listener.stop()
    await hid.disconnect()
    print("\nManual control stopped. Disconnected.")

if __name__ == "__main__":
    asyncio.run(main()) 