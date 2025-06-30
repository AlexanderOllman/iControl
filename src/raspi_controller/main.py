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
        """Captures a single frame from the specified video device."""
        print("Capturing frame from video device...")
        cap = cv2.VideoCapture(device_index)
        if not cap.isOpened():
            print(f"Error: Could not open video device at index {device_index}.")
            return None, None, None

        # Allow camera to warm up
        await asyncio.sleep(1)

        ret, frame = cap.read()
        cap.release()

        if not ret:
            print("Error: Could not read frame.")
            return None, None, None

        height, width, _ = frame.shape
        cv2.imwrite(filename, frame)
        print(f"Frame captured ({width}x{height}) and saved to {filename}")
        return frame, width, height

    async def get_action_plan(self, image: np.ndarray, width: int, height: int, command: str):
        """Sends the image and command to Gemini and gets a JSON action plan."""
        print("Asking Gemini for an action plan...")
        prompt = f"""
        You are an AI assistant controlling a computer. You will be given a screenshot
        of the current screen and a command from the user. The screen resolution is {width}x{height}.

        Your task is to analyze the screenshot, understand the user's command, and create a
        step-by-step plan to accomplish the task.

        You MUST respond ONLY with a JSON list of commands. Do not include any other text,
        explanations, or markdown formatting. The JSON should be a valid list of objects.

        Available actions:
        1. {{ "action": "click", "x": <int>, "y": <int> }}: Clicks at a specific pixel coordinate.
        2. {{ "action": "type", "text": "<string>" }}: Types the given text.
        3. {{ "action": "sleep", "seconds": <float> }}: Waits for a specified number of seconds.

        User command: "{command}"
        """

        # Encode the cv2 frame (numpy array) to JPEG bytes
        success, encoded_image = cv2.imencode('.jpg', image)
        if not success:
            print("Error: Could not encode image to JPEG.")
            return None
        
        image_part = types.Part.from_bytes(
            data=encoded_image.tobytes(),
            mime_type='image/jpeg'
        )
        
        try:
            # Use asyncio.to_thread to run the blocking SDK call without freezing the event loop.
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model='gemini-2.5-flash',
                contents=[image_part, prompt] # Per best practices: image first, then text.
            )
            
            # Clean up the response to extract only the JSON part
            cleaned_response = response.text.strip().replace("```json", "").replace("```", "").strip()
            print(f"Gemini response: {cleaned_response}")
            
            action_plan = json.loads(cleaned_response)
            return action_plan
        except Exception as e:
            print(f"Error processing Gemini response: {e}")
            print(f"Raw response was: {getattr(e, 'response', '')}")
            return None

async def main():
    """Main execution loop."""
    hid = HIDController()
    vision = VisionController()

    if not await hid.connect():
        return

    try:
        while True:
            command = input("\nEnter your command (or 'quit' to exit): ")
            if command.lower() == 'quit':
                break

            frame, width, height = await vision.capture_frame()
            if frame is None:
                continue

            action_plan = await vision.get_action_plan(frame, width, height, command)

            if action_plan and isinstance(action_plan, list):
                print("\nExecuting action plan...")
                for item in action_plan:
                    action = item.get("action")
                    if action == "click":
                        await hid.click_at_position(item.get("x"), item.get("y"))
                    elif action == "type":
                        print(f"  - Typing: {item.get('text')}")
                        await hid.type_string(item.get("text"))
                    elif action == "sleep":
                        print(f"  - Sleeping for {item.get('seconds')} seconds")
                        await asyncio.sleep(item.get("seconds"))
                    else:
                        print(f"  - Unknown action: {action}")
                    await asyncio.sleep(0.5) # Small delay between actions
                print("Action plan finished.")
            else:
                print("Could not get a valid action plan from Gemini.")

    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        await hid.disconnect()

if __name__ == "__main__":
    asyncio.run(main()) 