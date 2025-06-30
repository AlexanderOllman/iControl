import asyncio
import os
import json
import cv2
import numpy as np
from bleak import BleakClient, BleakScanner
from google import genai
from google.genai import types
from PIL import Image
import time

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

    async def click_at_position(self, x: int, y: int, click=True):
        """
        Moves to an absolute screen position and optionally clicks.
        Uses a reset-to-origin trick for absolute positioning.
        """
        if click:
            print(f"  - Clicking at ({x}, {y})")
        else:
            print(f"  - Moving to center at ({x}, {y})")

        # 1. Reset cursor to top-left (0,0) by moving a large negative distance
        await self.move_mouse_relative(-32767, -32767)
        await asyncio.sleep(0.05)
        # 2. Move to the absolute target coordinates
        await self.move_mouse_relative(x, y)
        await asyncio.sleep(0.05)
        # 3. Perform the click if requested
        if click:
            await self._send_command("mc:left")

class VisionController:
    """Captures video frames and uses Gemini to decide actions."""
    def __init__(self, device_index=0):
        self.client = genai.Client()
        self.cap = None
        self.device_index = device_index
        self._initialize_capture()

    def _initialize_capture(self):
        """Initializes and configures the video capture device."""
        print(f"Initializing video capture on device {self.device_index}...")
        self.cap = cv2.VideoCapture(self.device_index, cv2.CAP_V4L2)

        if not self.cap.isOpened():
            print(f"FATAL: Could not open video device at index {self.device_index}.")
            self.cap = None
            return

        # Configure for 1920x1080 YUYV, which was successful in tests
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('Y', 'U', 'Y', 'V'))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        
        # Let settings apply
        time.sleep(1)
        
        width = self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        height = self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        print(f"Video capture initialized at {int(width)}x{int(height)}")

    def shutdown(self):
        """Releases the video capture device."""
        if self.cap:
            print("Releasing video capture device...")
            self.cap.release()

    def find_screen_bounds(self, frame: np.ndarray, min_area_ratio=0.10):
        """
        Finds the bounding box of the actual screen within a letterboxed frame.
        Returns (x, y, w, h) of the screen area, or None if not found.
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        # Use Otsu's binarization which automatically finds an optimal threshold
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if not contours:
            print("Warning: No contours found in image.")
            return None

        largest_contour = max(contours, key=cv2.contourArea)
        
        frame_area = frame.shape[0] * frame.shape[1]
        contour_area = cv2.contourArea(largest_contour)
        
        # If the contour is too small, it's probably noise. Return the whole frame.
        if contour_area < frame_area * min_area_ratio:
            print(f"Warning: Largest contour is only {contour_area / frame_area:.2%} of the frame. Assuming full frame.")
            return 0, 0, frame.shape[1], frame.shape[0]
            
        return cv2.boundingRect(largest_contour)

    def capture_frame(self, filename="capture.jpg"):
        """
        Captures a fresh frame from the open device by clearing the buffer.
        """
        if not self.cap or not self.cap.isOpened():
            print("Error: Capture device is not initialized.")
            return None

        # Read and discard 5 frames to clear the buffer of any stale ones
        for _ in range(5):
            self.cap.read()

        # Now, read the frame we actually want
        ret, frame = self.cap.read()

        if not ret:
            print("Error: Could not read a fresh frame.")
            return None

        height, width, _ = frame.shape
        cv2.imwrite(filename, frame)
        print(f"Frame captured ({width}x{height}) and saved to {filename}")
        return frame

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
            # The config object from the example. We are not forcing a mime type here,
            # as the prompt is strong enough to ensure JSON output.
            config = types.GenerateContentConfig(      
                thinking_config=types.ThinkingConfig(thinking_budget=0)
            ) 
            response = await asyncio.to_thread(
                self.client.models.generate_content,
                model='gemini-2.5-flash',
                contents=[image_part, prompt],
                config=config
            )
            elements = json.loads(response.text.strip().replace("```json", "").replace("```", "").strip())
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
    vision = VisionController(device_index=0) # Initialize with the working device index

    if vision.cap is None:
        print("Exiting due to video capture initialization failure.")
        vision.shutdown()
        return

    if not await hid.connect():
        vision.shutdown()
        return

    # Initialize cursor position
    print("\nInitializing cursor position...")
    initial_frame = vision.capture_frame()
    if initial_frame is not None:
        bounds = vision.find_screen_bounds(initial_frame)
        if bounds:
            sx, sy, sw, sh = bounds
            center_x = sx + sw // 2
            center_y = sy + sh // 2
            await hid.click_at_position(center_x, center_y, click=False)
    print("Cursor initialized.")

    try:
        while True:
            command = input("\nEnter your command (or 'quit' to exit): ")
            if command.lower() == 'quit':
                break

            # Stage 1: See
            full_frame = vision.capture_frame()
            if full_frame is None:
                continue

            # Find the actual screen within the frame
            screen_bounds = vision.find_screen_bounds(full_frame)
            if screen_bounds is None:
                continue
            
            sx, sy, sw, sh = screen_bounds
            
            # Crop the frame to just the screen content
            screen_crop = full_frame[sy:sy+sh, sx:sx+sw]
            cv2.imwrite("capture_cropped.jpg", screen_crop) # Save for debugging

            elements = await vision.get_visible_elements(screen_crop)

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
                
                # De-normalize coordinates relative to the CROPPED image
                y0_rel = int(box[0] / 1000 * sh)
                x0_rel = int(box[1] / 1000 * sw)
                y1_rel = int(box[2] / 1000 * sh)
                x1_rel = int(box[3] / 1000 * sw)

                # Calculate the center of the bounding box relative to the CROPPED image
                click_x_rel = x0_rel + (x1_rel - x0_rel) // 2
                click_y_rel = y0_rel + (y1_rel - y0_rel) // 2

                # Remap the relative coordinates to the FULL frame's coordinate space
                final_click_x = sx + click_x_rel
                final_click_y = sy + click_y_rel
                
                print(f"\nAction: Clicking on '{selected_element['label']}' at ({final_click_x}, {final_click_y})")
                await hid.click_at_position(final_click_x, final_click_y)
                print("Action finished.")

            else:
                print("No suitable element found to perform the action.")

    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        await hid.disconnect()
        vision.shutdown()

if __name__ == "__main__":
    asyncio.run(main()) 