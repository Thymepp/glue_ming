from flask import Flask, render_template, request, jsonify
import json
import os
import sys
from datetime import datetime, timedelta
import threading
import serial
import time

app = Flask(__name__)

BASE_DIR = os.path.dirname(__file__)

CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
DATA_FILE = os.path.join(BASE_DIR, "data.json")

last_mtime = 0
scanner_data = ""   # 🔌 shared scanner buffer

SUCCESS_COLOR = "#16a34a"
ERROR_COLOR = "#ef4444"

# ---------- SERIAL READER THREAD ----------

def serial_reader():
    global scanner_data

    try:
        ser = serial.Serial('/dev/ttyACM0', 9600, timeout=1)
        print("📡 Scanner connected on /dev/ttyACM0")

        buffer = ""

        while True:
            if ser.in_waiting:
                data = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                buffer += data

                if '\n' in buffer or '\r' in buffer:
                    lines = buffer.splitlines()
                    for line in lines:
                        if line.strip():
                            scanner_data = line.strip()
                            print("🔍 Scanned:", scanner_data)
                    buffer = ""

            time.sleep(0.05)

    except Exception as e:
        print("❌ Serial error:", e)


# ---------- Create files if missing ----------

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


# ---------- JSON helpers ----------

def load_json(file, default):
    try:
        with open(file) as f:
            return json.load(f)
    except:
        return default


def load_config():
    return load_json(CONFIG_FILE, {
        "alarm_delay": 0.5,
        "expire_delay": 1.5,
        "dark_mode": True
    })


def load_data():
    return load_json(DATA_FILE, [])


def save_config(data):
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f, indent=4)


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)


# ---------- Auto reload config ----------

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
    lots = load_data()
    config = load_config()
    return render_template("index.html", lots=lots, config=config)


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
            "status": f"Error at line: {sys.exc_info()[-1].tb_lineno} {e}",
            "status_color": ERROR_COLOR
        })


# ---------- 🔥 SCANNER API ----------

@app.route("/api/scan")
def api_scan():
    global scanner_data

    try:
        lot = scanner_data
        scanner_data = ""  # clear after read

        if not lot:
            return jsonify({"lot": None})

        lots = load_data()
        config = load_config()

        # duplicate check
        for l in lots:
            if l["lot"] == lot:
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
            "status": f"Error at line: {sys.exc_info()[-1].tb_lineno} {e}",
            "status_color": ERROR_COLOR
        })


@app.route("/delete_lot", methods=["POST"])
def delete_lot():
    try:
        data = request.get_json()
        lot_to_delete = data.get("lot")

        lots = load_data()
        new_lots = [lot for lot in lots if lot["lot"] != lot_to_delete]
        save_data(new_lots)

        return jsonify({
            "status": f"🗑️ Lot {lot_to_delete} deleted",
            "status_color": SUCCESS_COLOR
        })

    except Exception as e:
        return jsonify({
            "status": f"Error at line: {sys.exc_info()[-1].tb_lineno} {e}",
            "status_color": ERROR_COLOR
        })


@app.route("/api/lots")
def api_lots():
    lots = load_data()
    return jsonify(process_lots(lots))


# ---------- PROCESS ----------

def process_lots(lots):
    now = datetime.now()

    for lot in lots:
        alarm_time = datetime.strptime(lot["alarm"], "%Y-%m-%d %H:%M:%S")
        expire_time = datetime.strptime(lot["expire"], "%Y-%m-%d %H:%M:%S")

        diff_sec = int((expire_time - now).total_seconds())
        if diff_sec < 0:
            diff_sec = 0

        minutes = diff_sec // 60
        seconds = diff_sec % 60

        lot["remain_text"] = f"{minutes}m {seconds:02d}s"

        if now >= expire_time:
            lot["status"] = "Expired"
        elif now >= alarm_time:
            lot["status"] = "Alarm"
        else:
            lot["status"] = "Active"

    return lots


# ---------- RUN ----------

if __name__ == "__main__":
    app.config.update(load_config())
    reload_config_if_changed()

    # 🔌 START SERIAL THREAD
    threading.Thread(target=serial_reader, daemon=True).start()

    app.run(host="0.0.0.0", port=5000, debug=True)