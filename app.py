from flask import Flask, render_template, request, jsonify
import json
import os
import sys
from datetime import datetime, timedelta

app = Flask(__name__)

BASE_DIR = os.path.dirname(__file__)

CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
DATA_FILE = os.path.join(BASE_DIR, "data.json")

last_mtime = 0

SUCCESS_COLOR = "#16a34a"
ERROR_COLOR = "#ef4444"

# ---------- Create files if missing ----------

if not os.path.exists(CONFIG_FILE):
    with open(CONFIG_FILE, "w") as f:
        json.dump({
            "alarm_delay": 0.0433,   # hours (~2.6 min)
            "expire_delay": 0.0833,  # hours (~5 min)
            "dark_mode": True
        }, f, indent=4)

if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, "w") as f:
        json.dump([], f, indent=4)


# ---------- Safe JSON loader ----------

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


# ---------- Save functions ----------

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


# ---------- Routes ----------

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
    param = {}
    try:
        data = request.json

        save_config(data)

        # update immediately (no delay)
        app.config.update(data)

        param["status"] = f"✅ Settings saved"
        param["status_color"] = SUCCESS_COLOR
    except Exception as e:
        param["status"] = f"Error at line: {sys.exc_info()[-1].tb_lineno} {e}"
        param["status_color"] = ERROR_COLOR

    return jsonify(param)


@app.route("/scan_lot", methods=["POST"])
def scan_lot():
    param = {}
    try:
        data = request.get_json()
        lot = data.get("lot")

        lots = load_data()
        config = load_config()

        # ✅ CHECK DUPLICATE
        for l in lots:
            if l["lot"] == lot:
                param["status"] = f"⚠️ Lot {lot} already exists"
                param["status_color"] = ERROR_COLOR
                return jsonify(param)

        now = datetime.now()

        # convert hours → minutes
        alarm_minutes = config.get("alarm_delay", 0) * 60
        expire_minutes = config.get("expire_delay", 0) * 60

        new_lot = [{
            "lot": lot,
            "alarm": (now + timedelta(minutes=alarm_minutes)).strftime("%Y-%m-%d %H:%M:%S"),
            "expire": (now + timedelta(minutes=expire_minutes)).strftime("%Y-%m-%d %H:%M:%S"),
            "isalarm": None
        }]

        lots = new_lot + lots

        save_data(lots)

        param["status"] = f"✅ Lot {lot} saved"
        param["status_color"] = SUCCESS_COLOR

    except Exception as e:
        param["status"] = f"Error at line: {sys.exc_info()[-1].tb_lineno} {e}"
        param["status_color"] = ERROR_COLOR

    return jsonify(param)


@app.route("/delete_lot", methods=["POST"])
def delete_lot():
    param = {}
    try:
        data = request.get_json()
        lot_to_delete = data.get("lot")

        lots = load_data()

        # filter out the lot
        new_lots = [lot for lot in lots if lot["lot"] != lot_to_delete]

        save_data(new_lots)

        param["status"] = f"🗑️ Lot {lot_to_delete} deleted"
        param["status_color"] = SUCCESS_COLOR

    except Exception as e:
        param["status"] = f"Error at line: {sys.exc_info()[-1].tb_lineno} {e}"
        param["status_color"] = ERROR_COLOR

    return jsonify(param)


@app.route("/api/lots")
def api_lots():
    lots = load_data()
    lots = process_lots(lots)
    return jsonify(lots)

def process_lots(lots):
    now = datetime.now()

    for lot in lots:
        alarm_time = datetime.strptime(lot["alarm"], "%Y-%m-%d %H:%M:%S")
        expire_time = datetime.strptime(lot["expire"], "%Y-%m-%d %H:%M:%S")

        # ===== REMAIN TIME =====
        diff_sec = int((expire_time - now).total_seconds())
        if diff_sec < 0:
            diff_sec = 0

        minutes = diff_sec // 60
        seconds = diff_sec % 60

        lot["remain_text"] = f"{minutes}m {seconds:02d}s"

        # ===== STATUS =====
        if now >= expire_time:
            lot["status"] = "Expired"
        elif now >= alarm_time:
            lot["status"] = "Alarm"
        else:
            lot["status"] = "Active"

    return lots


# ---------- Run ----------

if __name__ == "__main__":
    # load config at startup
    app.config.update(load_config())

    reload_config_if_changed()

    app.run(debug=True)