import os
import json
import time
import socket
import threading
from datetime import datetime, timedelta
import atexit
import signal
from flask import Flask, render_template, request, jsonify
import serial
import lgpio
from rotating_logger import AppLogger, DEBUG


SUCCESS_COLOR = "#16a34a"
ERROR_COLOR = "#ef4444"

class SVIAXCGlueApp:
    def __init__(self, base_dir=None):
        self.base_dir = base_dir or os.path.dirname(__file__)
        self.config_file = os.path.join(self.base_dir, "config.json")
        self.data_file = os.path.join(self.base_dir, "data.json")

        # Logger
        self.logger = AppLogger(
            name="sviaxcglueapp_log",
            log_dir=os.path.join(self.base_dir, "logs"),
            max_bytes=10 * 1024 * 1024,
            backup_count=5,
            log_level=DEBUG,
            console_output=True,
            use_colored_console=True
        )

        self.logger.info("Starting SVI Flask App")

        self.system_running = False
        self.socket_server_running = False

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
        self.data_lock = threading.Lock()
        self.last_scan = ""
        self.last_scan_time = 0

        self.last_mtime = 0

        atexit.register(self.cleanup)
        # signal
        signal.signal(signal.SIGTERM, self.handle_exit)
        signal.signal(signal.SIGINT, self.handle_exit)

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
            # self.logger.error(f"Failed to load JSON {file}: {e}")
            return default

    def load_config(self): return self.load_json(self.config_file, {})
    def save_config(self, data):
        with open(self.config_file, "w") as f: json.dump(data, f, indent=4)
        self.logger.debug(f"Config saved {data=}")

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
                if self.system_running:
                    lots = self.load_data()
                    lots = self.process_lots(lots)

                    sensor = self.read_sensor()

                    lot = next((lot for lot in lots if lot["is_activate"] != "Not activate"), None)

                    alarm_low = lot and (not lot.get("is_alarm_or_low", False) and (sensor == "Low" or lot.get("status") == "Alarm"))
                    alarm_empty = lot and (not lot.get("is_expire_or_empty", False) and (sensor == "Empty" or lot.get("status") == "Expired"))

                    if alarm_low or alarm_empty:
                        self.led_reset_on()
                        # self.alarm_on()
                    else:
                        self.led_reset_off()
                        # self.alarm_off()

                    if self.is_reset_btn_press() and (alarm_low or alarm_empty):
                        time.sleep(0.5)
                        if self.is_reset_btn_press() and (alarm_low or alarm_empty):
                            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            if alarm_low:
                                lot["is_alarm_or_low"] = now_str
                                self.logger.info(f"Alarm or Low reset {lot=} {now_str}")
                            if alarm_empty:
                                lot["is_expire_or_empty"] = now_str
                                self.logger.info(f"Expire or empty reset {lot=} {now_str}")
                            with self.data_lock:
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

    # ---------------- Server ----------------
    def socket_listener(self, host="0.0.0.0", port=5000):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            server.bind((host, port))
            server.listen(5)

            self.socket_server_running = True
            self.logger.info(f"Socket server listening on {host}:{port}")

            while True:
                try:
                    client, addr = server.accept()

                    self.socket_server_running = True
                    self.logger.info(f"Client connected: {addr}")

                    threading.Thread(
                        target=self.handle_client,
                        args=(client, addr),
                        daemon=True
                    ).start()

                except Exception as e:
                    self.socket_server_running = False
                    self.logger.error(f"Accept error: {e}")
                    time.sleep(1)

        except Exception as e:
            self.socket_server_running = False
            self.logger.error(f"Socket server error: {e}")

    def handle_client(self, client, addr):
        try:
            data = client.recv(4096)
            if not data:
                return

            # message = data.decode("utf-8")
            # self.logger.info(f"Received from {addr}: {message}")

            try:
                # parsed = json.loads(message)
                parsed = {
    "Glue_Data": {
        "Workorder": "WO456",
        "P/N": "ABC123",
        "Date&Time": "2026-04-01 14:30:00"
    }
}

                glue_data = parsed.get("Glue_Data", {})
                part_no = glue_data.get("P/N")
                wo = glue_data.get("Workorder")
                dt = glue_data.get("Date&Time")

                self.logger.info(f"Parsed -> P/N: {part_no}, WO: {wo}, Time: {dt}")

                with self.data_lock:
                    lots = self.load_data()

                    if any(l["lot"] == part_no for l in lots):
                        self.logger.warning(f"Duplicate lot: {part_no}")
                        return

                    new_entry = {
                        "timestamp": dt,
                        "wo": wo,
                        "lot": part_no,
                        "status": "Active",
                        "is_activate": "Not activate",
                        "remain_text": "Not activate",
                        "is_alarm_or_low": None,
                        "is_expire_or_empty": None,
                        "alarm": "-",
                        "expire": "-"
                    }

                    lots.insert(0, new_entry)
                    self.save_data(lots)
                    self.logger.info(f"insert 0 {new_entry=}")

            except json.JSONDecodeError:
                self.logger.error("Invalid JSON received")

        except Exception as e:
            self.logger.error(f"Client handling error: {e}")
        finally:
            client.close()
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

        @self.app.route("/api/socket_status")
        def socket_status():
            return {"socket_server": "online" if self.socket_server_running else "offline", "port": 5000}

        @self.app.route("/api/sensor")
        def api_sensor():
            return {"status": "System disconnected"} if not self.system_running else {"status": self.read_sensor()}

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
                return {"lot": None, "status": f"{lot} Lost Magnet or sensor not FULL","status_color":ERROR_COLOR}

            with self.data_lock:
                lots = self.load_data()
                latest_lot = lots[0] if lots else {}
                if latest_lot.get("lot") == lot:
                    if latest_lot.get("is_activate") == "Not activate":
                        latest_lot["is_activate"] = "Activate"
                        latest_lot["remain_text"] = "Activate"
                        now = datetime.now()
                        config = self.load_config()
                        alarm_minutes = config.get("alarm_delay",0)*60
                        expire_minutes = config.get("expire_delay",0)*60

                        latest_lot["alarm"] = (now+timedelta(minutes=alarm_minutes)).strftime("%Y-%m-%d %H:%M:%S")
                        latest_lot["expire"] = (now+timedelta(minutes=expire_minutes)).strftime("%Y-%m-%d %H:%M:%S")

                        self.save_data(lots)
                        self.logger.info(f"Activate {latest_lot=}")
                        return {"lot": lot, "status": f"Lot {lot} received", "status_color": SUCCESS_COLOR}

                    return {"lot": lot, "status": f"Lot {lot} already activated", "status_color": SUCCESS_COLOR}

                return {"lot": lot, "status": f"Lot {lot} is not latest", "status_color": ERROR_COLOR}

        @self.app.route("/delete_lot", methods=["POST"])
        def delete_lot():
            try:
                data = request.get_json()
                lot_to_delete = data.get("lot")
                with self.data_lock:
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
            with self.data_lock:
                lots = self.load_data()
            return self.process_lots(lots)

    # ---------------- Utilities ----------------
    def process_lots(self, lots):
        now = datetime.now()
        for lot in lots:
            if lot["is_activate"] == "Activate":
                alarm_time = datetime.strptime(lot["alarm"], "%Y-%m-%d %H:%M:%S")
                expire_time = datetime.strptime(lot["expire"], "%Y-%m-%d %H:%M:%S")
                diff = max(0,int((expire_time-now).total_seconds()))
                lot["remain_text"] = f"{diff//60}m {diff%60:02d}s"
                if now>=expire_time: lot["status"]="Expired"
                elif now>=alarm_time: lot["status"]="Alarm"
                else: lot["status"]="Active"
        return lots

    def cleanup(self):
        try:
            if self.h:
                self.alarm_off()
                self.led_reset_off()
                lgpio.gpiochip_close(self.h)
                self.logger.info("GPIO cleaned up")
                self.h = None
        except Exception as e:
            self.logger.error(f"Cleanup error: {e}")

    def handle_exit(self, signum, frame):
        self.logger.info(f"Shutting down (signal {signum})...")
        self.cleanup()
        os._exit(0)

    # ---------------- Run ----------------
    def run(self):
        threading.Thread(target=self.serial_reader, daemon=True).start()
        threading.Thread(target=self.monitor_buttons, daemon=True).start()
        threading.Thread(target=self.monitor_alarm, daemon=True).start()

        threading.Thread(target=self.socket_listener, daemon=True).start()

        self.app.config.update(self.load_config())
        self.logger.info("Flask app running on 0.0.0.0:5001")
        self.app.run(host="0.0.0.0", port=5001, use_reloader=False)


if __name__=="__main__":
    app_instance = SVIAXCGlueApp()
    app_instance.run()