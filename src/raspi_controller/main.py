import asyncio
import os
import json
import cv2
import numpy as np
from bleak import BleakClient, BleakScanner
from google import genai
from google.genai import types
from PIL import Image

# --- Configuration ---
# BLE settings for the ESP32-S3
DEVICE_NAME = "iControl HID"
SERVICE_UUID = "c48e6067-5295-48d3-8d5c-0395f61792b1"
CHARACTERISTIC_UUID = "c48e6068-5295-48d3-8d5c-0395f61792b1"

# --- Gemini API Setup ---
# IMPORTANT: Set your Gemini API key as an environment variable before running.
# The google-generativeai library will automatically use it.
# In your terminal, run:
# export GEMINI_API_KEY='YOUR_API_KEY'
try:
    # This check ensures the script fails early if the key isn't set.
    os.environ["GEMINI_API_KEY"]
except KeyError:
    print("="*60)
    print("ERROR: GEMINI_API_KEY environment variable not set.")
    print("Please set it by running: export GEMINI_API_KEY='YOUR_API_KEY'")
    print("="*60)
    exit()

class HIDController:
    """Manages the BLE connection and sends basic HID commands."""
    def __init__(self):
        self.client: BleakClient = None

    async def connect(self):
        print(f"Scanning for '{DEVICE_NAME}'...")
        device = await BleakScanner.find_device_by_name(DEVICE_NAME)
        if device is None:
            print(f"Could not find device with name '{DEVICE_NAME}'")
            return False
        print(f"Connecting to {device.name} ({device.address})...")
        self.client = BleakClient(device)
        try:
            await self.client.connect()
            print("Connected to HID device!")
            return True
        except Exception as e:
            print(f"Failed to connect: {e}")
            self.client = None
            return False

    async def disconnect(self):
        if self.client and self.client.is_connected:
            await self.client.disconnect()
            print("Disconnected from HID device.")
        self.client = None

    async def _send_command(self, command: str):
        if not self.client or not self.client.is_connected:
            print("Error: Not connected to HID device.")
            return
        try:
            await self.client.write_gatt_char(CHARACTERISTIC_UUID, bytearray(command, 'utf-8'), response=False)
        except Exception as e:
            print(f"Failed to send command: {e}")

    async def type_string(self, text: str):
        await self._send_command(f"k:{text}")

    async def move_mouse_relative(self, x: int, y: int):
        """Moves the mouse by a relative offset."""
        await self._send_command(f"m:{x},{y}")

    async def click_at_position(self, x: int, y: int):
        """
        Moves to an absolute screen position and clicks.
        Uses a reset-to-origin trick for absolute positioning.
        """
        print(f"  - Clicking at ({x}, {y})")
        # 1. Reset cursor to top-left (0,0) by moving a large negative distance
        await self.move_mouse_relative(-32767, -32767)
        await asyncio.sleep(0.05)
        # 2. Move to the absolute target coordinates
        await self.move_mouse_relative(x, y)
        await asyncio.sleep(0.05)
        # 3. Perform the click
        await self._send_command("mc:left")

class VisionController:
    """Captures video frames and uses Gemini to decide actions."""
    def __init__(self):
        self.client = genai.Client()

    async def capture_frame(self, device_index=0, filename="capture.jpg"):
        """
        Captures a single frame from the specified video device at its
        highest possible resolution.
        """
        print("Capturing frame from video device...")
        cap = cv2.VideoCapture(device_index)
        if not cap.isOpened():
            print(f"Error: Could not open video device at index {device_index}.")
            return None, None, None

        # Set a very high resolution to force the driver to the max
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 4096)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 2160)

        # Allow camera to warm up and settings to apply
        await asyncio.sleep(1)

        ret, frame = cap.read()
        
        # Get the actual resolution
        height, width, _ = frame.shape
        cap.release()

        if not ret:
            print("Error: Could not read frame.")
            return None, None, None

        cv2.imwrite(filename, frame)
        print(f"Frame captured ({width}x{height}) and saved to {filename}")
        return frame, width, height

    async def get_visible_elements(self, image: np.ndarray):
        """Sends an image to Gemini and asks it to identify UI elements."""
        print("Asking Gemini to identify UI elements...")
        prompt = """
        Analyze the provided screenshot and identify all significant and clickable UI elements.
        Return a JSON list where each entry represents an element. Each entry must contain:
        1. "label": A concise and descriptive text label for the element (e.g., "Notes App Icon", "Search Bar", "Settings Gear").
        2. "box_2d": The bounding box for the element as a list of four numbers [y_min, x_min, y_max, x_max] normalized to 1000.

        Do not identify the phone's status bar elements like time or battery. Focus on interactable application icons and widgets.
        Respond with ONLY the JSON list. Do not use markdown.
        """
        
        success, encoded_image = cv2.imencode('.jpg', image)
        if not success:
            print("Error encoding image")
            return None

        image_part = types.Part.from_bytes(data=encoded_image.tobytes(), mime_type='image/jpeg')

        try:
            config = types.GenerationConfig(response_mime_type="application/json")
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model='gemini-2.5-flash',
                contents=[image_part, prompt],
                config=config
            )
            elements = json.loads(response.text)
            return elements
        except Exception as e:
            print(f"Error getting UI elements from Gemini: {e}")
            return None

    async def choose_element_to_click(self, elements: list, command: str):
        """Asks Gemini which of the identified elements to click based on the user's command."""
        print("Asking Gemini which element to click...")
        
        # Format the list for the prompt
        formatted_elements = "\n".join([f'{i+1}: {element["label"]}' for i, element in enumerate(elements)])

        prompt = f"""
        Given the user's command: '{command}'
        And the following list of UI elements I can see on the screen:
        {formatted_elements}

        Which element number should be clicked to satisfy the user's command?
        Respond with ONLY the number corresponding to the element in the list.
        If no element is a clear match, respond with the number 0.
        """
        
        try:
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model='gemini-2.5-flash',
                contents=[prompt]
            )
            choice = int(response.text.strip())
            return choice
        except Exception as e:
            print(f"Error getting choice from Gemini: {e}")
            return 0

async def main():
    """Main execution loop for vision-driven control."""
    hid = HIDController()
    vision = VisionController()

    if not await hid.connect():
        return

    try:
        while True:
            command = input("\nEnter your command (or 'quit' to exit): ")
            if command.lower() == 'quit':
                break

            # Stage 1: See
            frame, width, height = await vision.capture_frame()
            if frame is None:
                continue

            elements = await vision.get_visible_elements(frame)

            if not elements or not isinstance(elements, list):
                print("Could not identify any UI elements.")
                continue

            print("\nI can see the following elements:")
            for i, element in enumerate(elements):
                print(f"  {i+1}: {element['label']}")

            # Stage 2: Decide and Act
            choice = await vision.choose_element_to_click(elements, command)

            if choice > 0 and choice <= len(elements):
                selected_element = elements[choice - 1]
                box = selected_element['box_2d']
                
                # De-normalize coordinates from 0-1000 to pixel values
                y0 = int(box[0] / 1000 * height)
                x0 = int(box[1] / 1000 * width)
                y1 = int(box[2] / 1000 * height)
                x1 = int(box[3] / 1000 * width)

                # Calculate the center of the bounding box
                click_x = x0 + (x1 - x0) // 2
                click_y = y0 + (y1 - y0) // 2
                
                print(f"\nAction: Clicking on '{selected_element['label']}' at ({click_x}, {click_y})")
                await hid.click_at_position(click_x, click_y)
                print("Action finished.")

            else:
                print("No suitable element found to perform the action.")

    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        await hid.disconnect()

if __name__ == "__main__":
    asyncio.run(main()) 