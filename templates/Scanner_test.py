import serial
import time

PORT = '/dev/ttyUSB0'   # change if needed (e.g. /dev/serial0)
BAUDRATE = 9600         # adjust to your scanner
TIMEOUT = 1

def main():
    try:
        ser = serial.Serial(
            port=PORT,
            baudrate=BAUDRATE,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=TIMEOUT
        )

        print(f"✅ Connected to {PORT} at {BAUDRATE} baud")
        print("📡 Waiting for scan... (Press Ctrl+C to exit)\n")

        buffer = ""

        while True:
            if ser.in_waiting > 0:
                data = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                buffer += data

                # If scanner sends newline → process line
                if '\n' in buffer or '\r' in buffer:
                    lines = buffer.splitlines()
                    for line in lines:
                        if line.strip():
                            print(f"🔍 Scanned: {line.strip()}")
                    buffer = ""

            time.sleep(0.05)

    except serial.SerialException as e:
        print(f"❌ Serial error: {e}")
        print("👉 Check port and permissions")
    except KeyboardInterrupt:
        print("\n👋 Exiting...")
    finally:
        try:
            ser.close()
        except:
            pass

if __name__ == "__main__":
    main()