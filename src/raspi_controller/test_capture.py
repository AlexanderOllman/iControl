import cv2
import time

def test_capture(device_index=0, filename="test_capture.jpg"):
    """
    A minimal script to test video capture functionality.
    It sets a known-good resolution and format and saves a single frame.
    """
    print(f"Attempting to open video device at index {device_index}...")
    cap = cv2.VideoCapture(device_index)

    if not cap.isOpened():
        print(f"FATAL: Could not open video device at index {device_index}.")
        return

    print("Successfully opened video device.")

    # --- Set Capture Properties ---
    # Using 1920x1080 MJPG as a common, reliable fallback.
    width = 1920
    height = 1080
    fourcc = cv2.VideoWriter_fourcc('M', 'J', 'P', 'G')

    print(f"Setting format to MJPG and resolution to {width}x{height}...")
    cap.set(cv2.CAP_PROP_FOURCC, fourcc)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    # Verify the settings
    actual_fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
    actual_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    print(f"Device responded with format: {''.join([chr((actual_fourcc >> 8 * i) & 0xFF) for i in range(4)])}")
    print(f"Device responded with resolution: {actual_width}x{actual_height}")
    
    # Allow the camera to stabilize
    print("Waiting for 2 seconds for camera to stabilize...")
    time.sleep(2)

    # --- Read a single frame ---
    print("Attempting to read a frame...")
    ret, frame = cap.read()

    if not ret or frame is None:
        print("FATAL: Failed to read frame from the device.")
        cap.release()
        return

    print("Successfully read a frame.")

    # --- Save the frame ---
    try:
        cv2.imwrite(filename, frame)
        print(f"Successfully saved captured frame to '{filename}'")
    except Exception as e:
        print(f"FATAL: Could not save the frame. Error: {e}")

    # --- Release the camera ---
    print("Releasing video device.")
    cap.release()


if __name__ == "__main__":
    test_capture() 