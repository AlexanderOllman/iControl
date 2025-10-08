import cv2
import asyncio
import bleak
import os
from PIL import Image
import google.generativeai as genai
import json
import time

# --- Configuration ---
ESP32_ADDRESS = "34:B4:72:0A:7B:5E" 
# This is the characteristic UUID for our custom BLE service
UART_TX_CHARACTERISTIC_UUID = "c48e6068-5295-48d3-8d5c-0395f61792b1"

# Configure the Gemini API key
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY environment variable not set")
genai.configure(api_key=GEMINI_API_KEY)

# --- HID Keycodes (as defined in HID specification) ---
KEY_RIGHT_ARROW = 0x4F
KEY_LEFT_ARROW = 0x50
KEY_DOWN_ARROW = 0x51
KEY_UP_ARROW = 0x52
KEY_ESC = 0x29
KEY_RETURN = 0x28
KEY_TAB = 0x2B
KEY_HOME = 0x4A
KEY_END = 0x4D
KEY_PAGE_UP = 0x4B
KEY_PAGE_DOWN = 0x4E
KEY_DELETE = 0x4C
KEY_F11 = 0x44

# Global variable for the video capture
cap = None

def init_camera(device_index=0, width=1920, height=1080):
    """Initializes and holds the video capture object."""
    global cap
    if cap is not None:
        cap.release()
    
    cap = cv2.VideoCapture(device_index)
    if not cap.isOpened():
        raise IOError(f"Cannot open video device {device_index}")
    
    # It's important to set a resolution the device supports.
    # 1920x1080 is common for many capture cards.
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    
    # Let the camera warm up
    time.sleep(2) 
    print(f"Camera initialized on /dev/video{device_index}")
    # Read a few frames to flush the buffer
    for _ in range(5):
        cap.read()
    print("Camera buffer flushed.")


def capture_frame_from_device():
    """Captures a single frame from the initialized video device."""
    global cap
    if cap is None or not cap.isOpened():
        print("Camera not initialized. Initializing now...")
        init_camera()
        if cap is None or not cap.isOpened():
             print("Failed to initialize camera.")
             return None

    ret, frame = cap.read()
    # Flush buffer by reading a few frames
    for _ in range(3):
        ret, frame = cap.read()

    if not ret:
        print("Failed to grab frame")
        # Try to re-initialize camera on failure
        init_camera()
        ret, frame = cap.read()
        if not ret:
            print("Still failing to grab frame after re-init.")
            return None
            
    return frame

def find_iphone_screen(frame, min_area_ratio=0.10):
    """
    Finds the largest contour in the frame that could be the iPhone screen,
    and returns the cropped image.
    """
    if frame is None:
        return None, None
        
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _, thresh = cv2.threshold(blurred, 30, 255, cv2.THRESH_BINARY)
    
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if not contours:
        return None, None
        
    frame_area = frame.shape[0] * frame.shape[1]
    min_area = frame_area * min_area_ratio
    
    largest_contour = None
    max_area = 0
    
    for contour in contours:
        area = cv2.contourArea(contour)
        if area > min_area and area > max_area:
            largest_contour = contour
            max_area = area

    if largest_contour is not None:
        x, y, w, h = cv2.boundingRect(largest_contour)
        # Add a small buffer/margin
        margin = 5
        x = max(0, x - margin)
        y = max(0, y - margin)
        w = min(frame.shape[1] - x, w + 2 * margin)
        h = min(frame.shape[0] - y, h + 2 * margin)
        
        cropped_frame = frame[y:y+h, x:x+w]
        return cropped_frame, (x, y, w, h)
        
    return None, None


async def send_command_to_esp32(client, command):
    """Sends a command string to the ESP32 over BLE."""
    if client and client.is_connected:
        try:
            await client.write_gatt_char(UART_TX_CHARACTERISTIC_UUID, command.encode('utf-8'))
            print(f"Sent: {command}")
        except Exception as e:
            print(f"Failed to send command: {e}")
    else:
        print("Not connected to ESP32.")

async def perform_voiceover_action(client, action, text=None, params=None):
    """Constructs and sends the correct command based on the action."""
    if action == "next":
        await send_command_to_esp32(client, f"ko_special:{KEY_RIGHT_ARROW}")
    elif action == "previous":
        await send_command_to_esp32(client, f"ko_special:{KEY_LEFT_ARROW}")
    elif action == "activate":
        await send_command_to_esp32(client, f"ko: ") # Space bar
    elif action == "home":
        await send_command_to_esp32(client, "ko:h")
    elif action == "back":
        await send_command_to_esp32(client, f"kh:{KEY_ESC}")
    elif action == "scroll_up":
        await send_command_to_esp32(client, f"ko_special:{KEY_UP_ARROW}")
    elif action == "scroll_down":
        await send_command_to_esp32(client, f"ko_special:{KEY_DOWN_ARROW}")
    elif action == "first_item":
        await send_command_to_esp32(client, f"ko_special:{KEY_HOME}")
    elif action == "last_item":
        await send_command_to_esp32(client, f"ko_special:{KEY_END}")
    elif action == "rotor_next":
        await send_command_to_esp32(client, "vo_rotor:next")
    elif action == "rotor_previous":
        await send_command_to_esp32(client, "vo_rotor:previous")
    elif action == "status_bar":
        await send_command_to_esp32(client, "ko:m")
    elif action == "notification_center":
        await send_command_to_esp32(client, "ko:n")
    elif action == "control_center":
        await send_command_to_esp32(client, "ko:c")
    elif action == "item_chooser":
        await send_command_to_esp32(client, "ko:i")
    elif action == "magic_tap":
        await send_command_to_esp32(client, "ko:z")
    elif action == "type" and text:
        # First, activate the text field if needed (often the current focus)
        await send_command_to_esp32(client, f"ko: ") 
        await asyncio.sleep(0.5)
        # Then, type the text
        await send_command_to_esp32(client, f"k:{text}")
        await asyncio.sleep(0.5)
        # Then, press return
        await send_command_to_esp32(client, f"kh:{KEY_RETURN}")
    elif action == "wait":
        # Just wait for specified seconds
        wait_time = params.get("seconds", 2) if params else 2
        await asyncio.sleep(wait_time)
    elif action == "ping":
        # Test connection
        await send_command_to_esp32(client, "ping")
    else:
        print(f"Unknown action: {action}")


async def get_next_action_from_gemini(objective, image_data, retry_count=3):
    """
    Sends the current screen and objective to Gemini and gets the next action.
    Includes retry logic for robustness.
    """
    if not image_data:
        print("No image data to send to Gemini.")
        return None

    model = genai.GenerativeModel('gemini-1.5-pro-latest')
    
    prompt = f"""
    You are an AI assistant controlling an iPhone via the VoiceOver accessibility feature.
    Your current high-level objective is: "{objective}".
    
    The user has provided you with the current screen capture. The black rectangle on the screen indicates the current VoiceOver focus.
    
    Based on the image and your objective, what is the single next action to take?
    Your response MUST be ONLY a valid JSON object with an "action" key. Do not include any other text, markdown formatting, or explanation.
    
    Available actions:
    Basic Navigation:
    - "next": Move to the next UI element
    - "previous": Move to the previous UI element
    - "activate": Tap/activate the currently focused element
    - "back": Go back to the previous screen
    - "home": Go to the home screen
    
    Advanced Navigation:
    - "scroll_up": Scroll up in the current view
    - "scroll_down": Scroll down in the current view
    - "first_item": Jump to the first item on screen
    - "last_item": Jump to the last item on screen
    - "rotor_next": Next rotor option
    - "rotor_previous": Previous rotor option
    
    System Controls:
    - "status_bar": Open status bar
    - "notification_center": Open notification center
    - "control_center": Open control center
    - "item_chooser": Open item chooser (list of all elements)
    - "magic_tap": Perform magic tap (play/pause media, answer calls, etc.)
    
    Text Input:
    - "type": Type text (requires "text" key with the string to type)
    
    Flow Control:
    - "done": Objective is complete
    - "wait": Wait a moment (optional "params": {"seconds": 3})

    Example Responses (respond with ONLY the JSON, no other text):
    {"action": "next"}
    {"action": "activate"}
    {"action": "type", "text": "Hello world"}
    {"action": "scroll_down"}
    {"action": "wait", "params": {"seconds": 3}}
    {"action": "done"}

    Current objective: "{objective}"
    """
    
    for attempt in range(retry_count):
        try:
            response = model.generate_content([prompt, image_data])
            
            # Clean up the response to extract the JSON
            text_response = response.text.strip()
            # Remove any markdown code blocks
            text_response = text_response.replace("```json", "").replace("```", "").strip()
            # Remove any leading/trailing text that's not JSON
            if '{' in text_response and '}' in text_response:
                start = text_response.find('{')
                end = text_response.rfind('}') + 1
                text_response = text_response[start:end]
            
            print(f"Gemini response (attempt {attempt + 1}): {text_response}")
            
            action_json = json.loads(text_response)
            
            # Validate the response has required fields
            if "action" not in action_json:
                print(f"Invalid response: missing 'action' field")
                if attempt < retry_count - 1:
                    await asyncio.sleep(1)  # Brief pause before retry
                    continue
            
            return action_json
            
        except json.JSONDecodeError as e:
            print(f"JSON parsing error (attempt {attempt + 1}): {e}")
            if 'response' in locals():
                print(f"Raw response was: {response.text}")
            if attempt < retry_count - 1:
                await asyncio.sleep(1)
                continue
                
        except Exception as e:
            print(f"Error getting action from Gemini (attempt {attempt + 1}): {e}")
            if 'response' in locals():
                print(f"Raw response was: {response.text}")
            if attempt < retry_count - 1:
                await asyncio.sleep(1)
                continue
    
    # If all retries failed, return a safe default
    print("All retry attempts failed. Returning 'wait' action.")
    return {"action": "wait", "params": {"seconds": 2}}


async def main():
    """Main control loop."""
    print("Initializing camera...")
    init_camera()

    print(f"Attempting to connect to ESP32 at {ESP32_ADDRESS}...")
    async with bleak.BleakClient(ESP32_ADDRESS) as client:
        if client.is_connected:
            print("Connected to ESP32!")
            
            # Test the connection
            print("Testing ESP32 connection...")
            await send_command_to_esp32(client, "ping")
            await asyncio.sleep(0.5)
            
            objective = input("What is your objective? (e.g., 'Open the notes app and write a new note') ")
            
            # Optional: Show available commands
            print("\nAvailable navigation commands:")
            print("- Basic: next, previous, activate, home, back")
            print("- Scrolling: scroll_up, scroll_down")
            print("- Jump: first_item, last_item")
            print("- System: status_bar, notification_center, control_center")
            print("- Advanced: rotor_next, rotor_previous, item_chooser, magic_tap")
            print("- Input: type (with text)")
            print("\nStarting automation...\n")
            
            for i in range(30): # Increased limit for complex tasks
                print(f"\n--- Step {i+1} ---")
                
                # 1. Capture and process frame
                frame = capture_frame_from_device()
                if frame is None:
                    print("Could not get frame, skipping step.")
                    await asyncio.sleep(2)
                    continue
                
                cropped_frame, _ = find_iphone_screen(frame)
                if cropped_frame is None:
                    print("Could not find iPhone screen in frame, using full frame.")
                    # Use the full frame as a fallback
                    pil_image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                else:
                    pil_image = Image.fromarray(cv2.cvtColor(cropped_frame, cv2.COLOR_BGR2RGB))
                
                # Save for debugging
                pil_image.save("capture_cropped.jpg")

                # 2. Get next action from Gemini
                action_data = await get_next_action_from_gemini(objective, pil_image)

                if not action_data or "action" not in action_data:
                    print("Could not determine next action. Stopping.")
                    break
                
                action = action_data.get("action")
                text_to_type = action_data.get("text")
                params = action_data.get("params")

                # 3. Perform action
                if action == "done":
                    print("Objective complete!")
                    break
                
                try:
                    await perform_voiceover_action(client, action, text_to_type, params)
                except Exception as e:
                    print(f"Error performing action '{action}': {e}")
                    # Continue to next iteration instead of crashing
                    await asyncio.sleep(1)
                
                # Wait for UI to update
                await asyncio.sleep(2) 
            else:
                print("Reached maximum step limit.")

        else:
            print("Failed to connect to ESP32.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        if cap is not None:
            cap.release()
        print("Camera released.") 