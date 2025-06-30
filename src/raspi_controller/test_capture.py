import cv2
import time
import subprocess

def test_capture_with_preconfig(device_index=0, filename="test_capture.jpg"):
    """
    A minimal script to test video capture functionality.
    It first uses a command-line tool (v4l2-ctl) to configure the device,
    then attempts to read a frame with OpenCV.
    """
    print("="*40)
    print(f"TESTING DEVICE: /dev/video{device_index}")
    print("="*40)
    
    device_path = f"/dev/video{device_index}"
    width = 1920
    height = 1080
    
    # --- Step 1: Pre-configure the device with v4l2-ctl ---
    print("Attempting to pre-configure device with v4l2-ctl...")
    command = [
        "v4l2-ctl",
        "-d", device_path,
        "--set-fmt-video", f"width={width},height={height},pixelformat=YUYV"
    ]
    
    try:
        # We use check=True so it will raise an exception if the command fails
        subprocess.run(command, check=True, capture_output=True, text=True)
        print("v4l2-ctl command executed successfully.")
    except FileNotFoundError:
        print("FATAL: 'v4l2-ctl' command not found. Please install with 'sudo apt-get install v4l-utils'")
        return
    except subprocess.CalledProcessError as e:
        print(f"FATAL: v4l2-ctl command failed.")
        print(f"  - Stderr: {e.stderr}")
        return

    # --- Step 2: Attempt to capture with OpenCV ---
    print(f"Attempting to open video device at index {device_index} with OpenCV...")
    cap = cv2.VideoCapture(device_index, cv2.CAP_V4L2)

    if not cap.isOpened():
        print(f"ERROR: OpenCV could not open video device at index {device_index} after pre-configuration.")
        return

    print("Successfully opened video device with OpenCV.")
    
    # Allow a moment to stabilize after configuration
    time.sleep(1)

    print("Attempting to read a frame...")
    ret, frame = cap.read()

    if not ret or frame is None:
        print("ERROR: Failed to read frame from the device.")
        cap.release()
        return

    print("Successfully read a frame.")

    try:
        cv2.imwrite(filename, frame)
        print(f"SUCCESS: Saved captured frame to '{filename}'")
    except Exception as e:
        print(f"ERROR: Could not save the frame. Error: {e}")

    print("Releasing video device.")
    cap.release()


if __name__ == "__main__":
    test_capture_with_preconfig(device_index=0, filename="test_capture_final.jpg") 