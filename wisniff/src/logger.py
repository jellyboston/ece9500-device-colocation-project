# for simple debug testing. ignore for integrated prod use.

import csv
import signal
import sys
import time
import serial

# --- CONFIGURATION ---
PORT = "COM6"          # Change to your ESP32 port (e.g., "/dev/ttyUSB0" on Linux/Mac)
BAUD_RATE = 921600     # Matches your Serial.begin(921600)
OUTPUT_FILE = "esp32_csi_data.csv"
# ---------------------

def main():
    print(f"Opening port {PORT} at {BAUD_RATE} baud...")
    try:
        ser = serial.Serial(PORT, BAUD_RATE, timeout=1.0)
        ser.reset_input_buffer()
    except serial.SerialException as e:
        print(f"Error opening serial port: {e}")
        return

    # Open CSV file in append mode with explicit newline behavior
    print(f"Logging data to: {OUTPUT_FILE}")
    print("Press Ctrl+C to stop safely.")
    
    with open(OUTPUT_FILE, mode="a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        last_flush = time.time()

        def signal_handler(sig, frame):
            print("\nClosing connection and saving file...")
            ser.close()
            sys.exit(0)
            
        signal.signal(signal.SIGINT, signal_handler)

        while True:
            try:
                # Read a full newline-terminated line from serial
                if ser.in_waiting > 0:
                    raw_line = ser.readline()
                    
                    try:
                        decoded_line = raw_line.decode("utf-8", errors="replace").strip()
                    except Exception:
                        continue

                    if not decoded_line:
                        continue

                    # If the line is an internal print debug/comment, display it but don't save as CSV rows
                    if decoded_line.startswith("#"):
                        print(decoded_line)
                        continue

                    # Split comma-separated tokens (CSI,..., or PKT,...)
                    row_data = [token.strip() for token in decoded_line.split(",")]
                    writer.writerow(row_data)

                    # Periodically flush data to disk every 1 second
                    if time.time() - last_flush > 1.0:
                        f.flush()
                        last_flush = time.time()

            except serial.SerialException as e:
                print(f"\nSerial connection lost: {e}")
                break
            except Exception as e:
                print(f"\nUnexpected error loop: {e}")
                break

if __name__ == "__main__":
    main()
