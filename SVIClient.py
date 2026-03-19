import requests
import logging
from rotating_logger import AppLogger, DEBUG

logger = logging.getLogger(__name__)


class SVIClient:
    def __init__(self, username, password, base_url="https://api.svi.co.th"):
        # ---------- LOGGER ----------
        self.logger = AppLogger(
            name="sviclient_log",
            log_dir="logs/production",
            max_bytes=50 * 1024 * 1024,
            backup_count=10,
            log_level=DEBUG,
            console_output=True,
            use_colored_console=True
        )

        self.base_url = base_url
        self.username = username
        self.password = password
        self.access_token = None
        self.refresh_token = None

    # -------------------------
    # AUTH
    # -------------------------
    def authenticate(self):
        url = f"{self.base_url}/api/token/"
        payload = {
            "username": self.username,
            "password": self.password
        }

        self.logger.info("Authenticating with SVI API...")

        try:
            res = requests.post(url, json=payload, timeout=5)

            if res.status_code == 200:
                tokens = res.json()
                self.access_token = tokens.get("access")
                self.refresh_token = tokens.get("refresh")

                self.logger.info("✅ SVI Auth success")
                return True
            else:
                self.logger.error(f"❌ Auth failed: {res.status_code} - {res.text}")
                return False

        except Exception as e:
            self.logger.exception("❌ Auth error")
            return False

    # -------------------------
    # SAVE ASSEMBLY
    # -------------------------
    def save_assembly(self, wo, sn, opname, operator_id):
        url = f"{self.base_url}/main/svi/apiSaveAssembly/"

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json"
        }

        data = {
            "wo": wo,
            "sn": sn,
            "opname": opname,
            "operatorID": operator_id
        }

        self.logger.debug(f"Sending save_assembly request: {data}")

        try:
            res = requests.post(url, json=data, headers=headers, timeout=5)

            # 🔁 Auto re-auth if expired
            if res.status_code == 401:
                self.logger.warning("🔄 Token expired → re-authenticating")

                if self.authenticate():
                    headers["Authorization"] = f"Bearer {self.access_token}"
                    res = requests.post(url, json=data, headers=headers, timeout=5)

            self.logger.info(f"Response status: {res.status_code}")
            self.logger.info(f"Response: {res.json()}")
            return res

        except Exception as e:
            self.logger.exception("❌ API error")
            return None


# -------------------------
# MAIN ENTRY POINT
# -------------------------
if __name__ == "__main__":
    # Example usage
    client = SVIClient(
        username="LDL_ASSEMBLY",
        password="1NmNf425l2"
    )

    if client.authenticate():
        response = client.save_assembly(
            wo="WO123456",
            sn="SN987654",
            opname="OP10",
            operator_id="EMP001"
        )

        if response:
            try:
                print("Response JSON:", response.json())
            except Exception:
                print("Raw response:", response.text)