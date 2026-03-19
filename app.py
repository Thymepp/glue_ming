import os
import json
import time
import threading
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify
import serial
import lgpio
from rotating_logger import AppLogger, DEBUG

SUCCESS_COLOR = "#16a34a"
ERROR_COLOR = "#ef4444"

class SVIFlaskApp:
    def __init__(self, base_dir=None):
        self.base_dir = base_dir or os.path.dirname(__file__)
        self.config_file = os.path.join(self.base_dir, "config.json")
        self.data_file = os.path.join(self.base_dir, "data.json")

        # Logger
        self.logger = AppLogger(
            name="sviflask_log",
            log_dir=os.path.join(self.base_dir, "logs"),
            max_bytes=10 * 1024 * 1024,
            backup_count=5,
            log_level=DEBUG,
            console_output=True,
            use_colored_console=True
        )

        self.logger.info("Starting SVI Flask App")

        self.system_running = False

        # GPIO
        self.CHIP = 0
        self.SENSORS = {"Empty": 20, "Low": 17, "Full": 16}
        self.BUTTON_START = 21
        self.BUTTON_RESET = 22
        self.BUZZER = 5
        self.LED_RESET = 4
        self.h = None

        # Scanner
        self.scanner_data = ""
        self.scanner_lock = threading.Lock()
        self.last_scan = ""
        self.last_scan_time = 0

        self.last_mtime = 0

        # Flask app
        self.app = Flask(__name__)
        self.setup_routes()
        self.init_files()
        self.init_gpio()

    # ---------------- GPIO ----------------
    def init_gpio(self):
        if self.h is None:
            self.h = lgpio.gpiochip_open(self.CHIP)
            for pin in list(self.SENSORS.values()) + [self.BUTTON_START, self.BUTTON_RESET]:
                lgpio.gpio_claim_input(self.h, pin, lgpio.SET_ACTIVE_LOW)
            for pin in [self.BUZZER, self.LED_RESET]:
                lgpio.gpio_claim_output(self.h, pin, 1)
        self.logger.info("GPIO initialized")

    def led_reset_on(self): lgpio.gpio_write(self.h, self.LED_RESET, 0)
    def led_reset_off(self): lgpio.gpio_write(self.h, self.LED_RESET, 1)
    def alarm_on(self): lgpio.gpio_write(self.h, self.BUZZER, 0)
    def alarm_off(self): lgpio.gpio_write(self.h, self.BUZZER, 1)
    def is_start_btn_press(self): return bool(lgpio.gpio_read(self.h, self.BUTTON_START))
    def is_reset_btn_press(self): return bool(lgpio.gpio_read(self.h, self.BUTTON_RESET))
    def read_sensor(self):
        e, l, f = [lgpio.gpio_read(self.h, self.SENSORS[x]) for x in ["Empty","Low","Full"]]
        if e == 1: return "Empty"
        elif l == 1: return "Low"
        elif f == 1: return "Full"
        return "Unknown"

    # ---------------- Files ----------------
    def init_files(self):
        if not os.path.exists(self.config_file):
            with open(self.config_file, "w") as f:
                json.dump({"alarm_delay":0.0433, "expire_delay":0.0833, "dark_mode":True}, f, indent=4)
            self.logger.info("Created default config.json")

        if not os.path.exists(self.data_file):
            with open(self.data_file, "w") as f:
                json.dump([], f, indent=4)
            self.logger.info("Created default data.json")

    def load_json(self, file, default):
        try:
            with open(file) as f: return json.load(f)
        except Exception as e:
            self.logger.error(f"Failed to load JSON {file}: {e}")
            return default

    def load_config(self): return self.load_json(self.config_file, {})
    def save_config(self, data):
        with open(self.config_file, "w") as f: json.dump(data, f, indent=4)
        self.logger.debug("Config saved")

    def load_data(self): return self.load_json(self.data_file, [])
    def save_data(self, data):
        with open(self.data_file, "w") as f: json.dump(data, f, indent=4)
        self.logger.debug("Data saved")

    # ---------------- Threads ----------------
    def monitor_buttons(self):
        while True:
            self.system_running = self.is_start_btn_press()
            time.sleep(0.1)

    def monitor_alarm(self):
        while True:
            try:
                lots = self.load_data()
                sensor = self.read_sensor()
                has_alarm = lots and lots[0].get("isalarm") is None
                is_expire = lots and lots[0]['status'] in ["Alarm","Expired"]
                sensor_alarm = sensor in ["Empty","Low"]

                if self.system_running and has_alarm and (sensor_alarm or is_expire):
                    self.led_reset_on()
                    self.alarm_on()
                else:
                    self.led_reset_off()
                    self.alarm_off()

                if self.system_running and self.is_reset_btn_press():
                    time.sleep(0.5)
                    if self.is_reset_btn_press():
                        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        for lot in lots:
                            if lot.get("isalarm") is None:
                                lot["isalarm"] = now_str
                        self.save_data(lots)
                        self.logger.info("Alarm reset by user")
                time.sleep(0.5)
            except Exception as e:
                self.logger.error(f"Alarm monitor error: {e}")

    def serial_reader(self):
        while True:
            try:
                ser = serial.Serial('/dev/ttyACM0', 9600, timeout=1)
                self.logger.info("Serial scanner connected")
                buffer = ""
                while True:
                    if ser.in_waiting:
                        data = ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                        buffer += data
                        if '\n' in buffer or '\r' in buffer:
                            lines = buffer.splitlines()
                            for line in lines:
                                lot = line.strip()
                                if not lot: continue
                                now = time.time()
                                if lot == self.last_scan and (now - self.last_scan_time) < 1:
                                    continue
                                self.last_scan = lot
                                self.last_scan_time = now
                                with self.scanner_lock:
                                    self.scanner_data = lot
                                self.logger.info(f"Scanned: {lot}")
                            buffer = ""
                    time.sleep(0.05)
            except Exception as e:
                self.logger.error(f"Serial error: {e}")
                time.sleep(2)

    # ---------------- Routes ----------------
    def setup_routes(self):
        @self.app.before_request
        def reload_config_if_changed():
            try:
                mtime = os.path.getmtime(self.config_file)
                if mtime != self.last_mtime:
                    self.app.config.update(self.load_config())
                    self.last_mtime = mtime
                    self.logger.debug("Config reloaded")
            except:
                pass

        @self.app.route("/")
        def index(): return render_template("index.html", config=self.load_config())

        @self.app.route("/api/system_status")
        def system_status(): return {"running": self.system_running}

        @self.app.route("/api/sensor")
        def api_sensor():
            if not self.system_running:
                return {"status":"System disconnected"}
            return {"status": self.read_sensor()}

        @self.app.route("/api/settings")
        def api_settings():
            config = self.load_config()
            return {
                "alarm_delay": config.get("alarm_delay"),
                "expire_delay": config.get("expire_delay"),
                "dark_mode": config.get("dark_mode")
            }

        @self.app.route("/save_settings", methods=["POST"])
        def save_settings():
            try:
                data = request.json
                self.save_config(data)
                self.app.config.update(data)
                return {"status":"✅ Settings saved","status_color":SUCCESS_COLOR}
            except Exception as e:
                self.logger.error(f"Save settings error: {e}")
                return {"status":f"Error: {e}","status_color":ERROR_COLOR}

        @self.app.route("/api/scan")
        def api_scan():
            with self.scanner_lock:
                lot = self.scanner_data
                self.scanner_data = ""

            if not self.system_running:
                return {"lot": None, "status":"System disconnected","status_color":ERROR_COLOR}

            if not lot:
                return {"lot": None}

            if self.read_sensor() != "Full":
                return {"lot": None, "status": f"{lot} Lost Magnet","status_color":ERROR_COLOR}

            lots = self.load_data()
            if any(l["lot"]==lot for l in lots):
                return {"lot": lot,"status": f"⚠️ Lot {lot} already exists","status_color":ERROR_COLOR}

            now = datetime.now()
            config = self.load_config()
            alarm_minutes = config.get("alarm_delay",0)*60
            expire_minutes = config.get("expire_delay",0)*60

            new_lot = {
                "lot": lot,
                "alarm": (now+timedelta(minutes=alarm_minutes)).strftime("%Y-%m-%d %H:%M:%S"),
                "expire": (now+timedelta(minutes=expire_minutes)).strftime("%Y-%m-%d %H:%M:%S"),
                "isalarm": None
            }

            lots.insert(0,new_lot)
            self.save_data(lots)
            self.logger.info(f"Lot {lot} saved")

            return {"lot": lot,"status": f"✅ Lot {lot} saved","status_color":SUCCESS_COLOR}

        @self.app.route("/delete_lot", methods=["POST"])
        def delete_lot():
            try:
                data = request.get_json()
                lot_to_delete = data.get("lot")
                lots = self.load_data()
                lots = [lot for lot in lots if lot["lot"] != lot_to_delete]
                self.save_data(lots)
                self.logger.info(f"Lot {lot_to_delete} deleted")
                return {"status": f"Lot {lot_to_delete} deleted","status_color":SUCCESS_COLOR}
            except Exception as e:
                self.logger.error(f"Delete lot error: {e}")
                return {"status":f"Error: {e}","status_color":ERROR_COLOR}

        @self.app.route("/api/lots")
        def api_lots():
            lots = self.load_data()
            return self.process_lots(lots)

    # ---------------- Utilities ----------------
    def process_lots(self, lots):
        now = datetime.now()
        for lot in lots:
            alarm_time = datetime.strptime(lot["alarm"], "%Y-%m-%d %H:%M:%S")
            expire_time = datetime.strptime(lot["expire"], "%Y-%m-%d %H:%M:%S")
            diff = max(0,int((expire_time-now).total_seconds()))
            lot["remain_text"] = f"{diff//60}m {diff%60:02d}s"
            if now>=expire_time: lot["status"]="Expired"
            elif now>=alarm_time: lot["status"]="Alarm"
            else: lot["status"]="Active"
        return lots

    # ---------------- Run ----------------
    def run(self):
        threading.Thread(target=self.serial_reader, daemon=True).start()
        threading.Thread(target=self.monitor_buttons, daemon=True).start()
        threading.Thread(target=self.monitor_alarm, daemon=True).start()
        self.app.config.update(self.load_config())
        self.logger.info("Flask app running on 0.0.0.0:5001")
        self.app.run(host="0.0.0.0", port=5001, use_reloader=False)


if __name__=="__main__":
    app_instance = SVIFlaskApp()
    app_instance.run()