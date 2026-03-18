from flask import Flask, render_template, request, jsonify
import json
import os
import sys
from datetime import datetime, timedelta
import threading
import serial
import time
import lgpio


app = Flask(__name__)

BASE_DIR = os.path.dirname(__file__)

CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
DATA_FILE = os.path.join(BASE_DIR, "data.json")

last_mtime = 0

# GPIO
CHIP = 0
# in
SENSORS = {"Empty": 20, "Low": 17, "Full": 16}
BUTTON_START = 21
BUTTON_RESET = 22
# out
BUZZER = 5
LED_RESET = 4

h = None
system_running = False

def monitor_buttons():
    global system_running

    while True:
        try:
            if is_start_btn_press():
                system_running = True
                # led_reset_off()
                # alarm_off()
            else:
                system_running = False
                # led_reset_on()
                # alarm_on()

            time.sleep(0.1)

        except Exception as e:
            print("Button error:", e)

def monitor_alarm():
    global system_running
    while True:
        try:
            lots = load_data()
            lots = process_lots(lots)

            has_alarm = any(
                lot["status"] in ["Alarm", "Expired"] and lot.get("isalarm") is None
                for lot in lots
            )

            sensor = read_sensor()
            sensor_alarm = sensor in ["Empty", "Low"]

            if system_running and (has_alarm or sensor_alarm):
                alarm_on()
                led_reset_on()
            else:
                alarm_off()
                led_reset_off()

            if is_reset_btn_press():
                time.sleep(0.5)
                if is_reset_btn_press():
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    for lot in lots:
                        if lot.get("isalarm") is None and lot["status"] in ["Alarm", "Expired"]:
                            lot["isalarm"] = now_str
                    save_data(lots)
                    alarm_off()
                    led_reset_off()

            time.sleep(0.5)

        except Exception as e:
            print("Alarm error:", e)
def init_gpio():
    global h
    if h is None:
        h = lgpio.gpiochip_open(CHIP)

        for pin in list(SENSORS.values()) + [BUTTON_START, BUTTON_RESET]:
            lgpio.gpio_claim_input(h, pin, lgpio.SET_ACTIVE_LOW)

        for pin in [BUZZER, LED_RESET]:
            lgpio.gpio_claim_output(h, pin, 1)

def led_reset_on():
    lgpio.gpio_write(h, LED_RESET, 0)

def led_reset_off():
    lgpio.gpio_write(h, LED_RESET, 1)

def alarm_on():
    lgpio.gpio_write(h, BUZZER, 0)

def alarm_off():
    lgpio.gpio_write(h, BUZZER, 1)

def is_start_btn_press():
    return bool(lgpio.gpio_read(h, BUTTON_START))

def is_reset_btn_press():
    return bool(lgpio.gpio_read(h, BUTTON_RESET))

def read_sensor():
    e = lgpio.gpio_read(h, SENSORS["Empty"])
    l = lgpio.gpio_read(h, SENSORS["Low"])
    f = lgpio.gpio_read(h, SENSORS["Full"])

    if e == 1:
        return "Empty"
    elif l == 1:
        return "Low"
    elif f == 1:
        return "Full"
    else:
        return "Full"   # default

# thread-safe scanner data
scanner_data = ""
scanner_lock = threading.Lock()

# prevent duplicate spam
last_scan = ""
last_scan_time = 0

SUCCESS_COLOR = "#16a34a"
ERROR_COLOR = "#ef4444"

# ---------- SERIAL READER ----------

def serial_reader():
    global scanner_data, last_scan, last_scan_time

    while True:
        try:
            ser = serial.Serial('/dev/ttyACM0', 9600, timeout=1)
            print("📡 Scanner connected")

            buffer = ""

            while True:
                if ser.in_waiting:
                    data = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                    buffer += data

                    if '\n' in buffer or '\r' in buffer:
                        lines = buffer.splitlines()

                        for line in lines:
                            lot = line.strip()
                            if not lot:
                                continue

                            now = time.time()

                            if lot == last_scan and (now - last_scan_time) < 1:
                                continue

                            last_scan = lot
                            last_scan_time = now

                            with scanner_lock:
                                scanner_data = lot

                            print("🔍 Scanned:", lot)

                        buffer = ""

                time.sleep(0.05)

        except Exception as e:
            print("❌ Serial error:", e)
            print("🔄 Reconnecting in 2 sec...")
            time.sleep(2)


# ---------- FILE INIT ----------

if not os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, "w") as f:
        json.dump({
            "alarm_delay": 0.0433,
            "expire_delay": 0.0833,
            "dark_mode": True
        }, f, indent=4)

if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w") as f:
        json.dump([], f, indent=4)


# ---------- JSON ----------

def load_json(file, default):
    try:
        with open(file) as f:
            return json.load(f)
    except:
        return default


def load_config():
    return load_json(CONFIG_FILE, {})


def load_data():
    return load_json(DATA_FILE, [])


def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=4)


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)


# ---------- CONFIG AUTO RELOAD ----------

def reload_config_if_changed():
    global last_mtime

    try:
        mtime = os.path.getmtime(CONFIG_FILE)
    except:
        return

    if mtime != last_mtime:
        app.config.update(load_config())
        last_mtime = mtime


@app.before_request
def check_config():
    reload_config_if_changed()


# ---------- ROUTES ----------

@app.route("/")
def index():
    return render_template("index.html", config=load_config())


@app.route("/api/system_status")
def system_status():
    return jsonify({
        "running": system_running
    })

@app.route("/api/sensor")
def api_sensor():
    return jsonify({
        "status": read_sensor()
    })

@app.route("/api/settings")
def api_settings():
    return jsonify({
        "alarm_delay": app.config.get("alarm_delay"),
        "expire_delay": app.config.get("expire_delay"),
        "dark_mode": app.config.get("dark_mode")
    })


@app.route("/save_settings", methods=["POST"])
def save_settings():
    try:
        data = request.json
        save_config(data)
        app.config.update(data)

        return jsonify({
            "status": "✅ Settings saved",
            "status_color": SUCCESS_COLOR
        })

    except Exception as e:
        return jsonify({
            "status": f"Error line {sys.exc_info()[-1].tb_lineno}: {e}",
            "status_color": ERROR_COLOR
        })


# ---------- SCAN API ----------

@app.route("/api/scan")
def api_scan():
    global scanner_data, system_running

    if not system_running:
        scanner_data = ""
        return jsonify({
            "lot": None,
            "status": "System disconnected",
            "status_color": ERROR_COLOR
        })

    try:
        with scanner_lock:
            lot = scanner_data
            scanner_data = ""

        if not lot:
            return jsonify({"lot": None})

        lots = load_data()
        config = load_config()

        # duplicate check
        if any(l["lot"] == lot for l in lots):
            return jsonify({
                "lot": lot,
                "status": f"⚠️ Lot {lot} already exists",
                "status_color": ERROR_COLOR
            })

        now = datetime.now()

        alarm_minutes = config.get("alarm_delay", 0) * 60
        expire_minutes = config.get("expire_delay", 0) * 60

        new_lot = {
            "lot": lot,
            "alarm": (now + timedelta(minutes=alarm_minutes)).strftime("%Y-%m-%d %H:%M:%S"),
            "expire": (now + timedelta(minutes=expire_minutes)).strftime("%Y-%m-%d %H:%M:%S"),
            "isalarm": None
        }

        lots.insert(0, new_lot)
        save_data(lots)

        return jsonify({
            "lot": lot,
            "status": f"✅ Lot {lot} saved",
            "status_color": SUCCESS_COLOR
        })

    except Exception as e:
        return jsonify({
            "status": f"Error line {sys.exc_info()[-1].tb_lineno}: {e}",
            "status_color": ERROR_COLOR
        })


@app.route("/delete_lot", methods=["POST"])
def delete_lot():
    try:
        data = request.get_json()
        lot_to_delete = data.get("lot")

        lots = load_data()
        lots = [lot for lot in lots if lot["lot"] != lot_to_delete]
        save_data(lots)

        return jsonify({
            "status": f"🗑️ Lot {lot_to_delete} deleted",
            "status_color": SUCCESS_COLOR
        })

    except Exception as e:
        return jsonify({
            "status": f"Error line {sys.exc_info()[-1].tb_lineno}: {e}",
            "status_color": ERROR_COLOR
        })


@app.route("/api/lots")
def api_lots():
    return jsonify(process_lots(load_data()))


# ---------- PROCESS ----------

def process_lots(lots):
    now = datetime.now()

    for lot in lots:
        alarm_time = datetime.strptime(lot["alarm"], "%Y-%m-%d %H:%M:%S")
        expire_time = datetime.strptime(lot["expire"], "%Y-%m-%d %H:%M:%S")

        diff = max(0, int((expire_time - now).total_seconds()))

        lot["remain_text"] = f"{diff//60}m {diff%60:02d}s"

        if now >= expire_time:
            lot["status"] = "Expired"
        elif now >= alarm_time:
            lot["status"] = "Alarm"
        else:
            lot["status"] = "Active"

    return lots


# ---------- RUN ----------

if __name__ == "__main__":
    init_gpio()

    app.config.update(load_config())

    reload_config_if_changed()

    threading.Thread(target=serial_reader, daemon=True).start()
    threading.Thread(target=monitor_buttons, daemon=True).start()
    threading.Thread(target=monitor_alarm, daemon=True).start()

    app.run(host="0.0.0.0", port=5001, use_reloader=False)