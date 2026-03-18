import lgpio
import time

# GPIO
CHIP = 0
SENSORS = {"Empty": 20, "Low": 17, "Full": 16}
BUTTON_START = 21 # in
BUTTON_RESET = 22 # in
BUZZER = 5 # out
LED_RESET = 4 # out

# เปิด chip
h = lgpio.gpiochip_open(CHIP)

# ตั้ง input (sensor + button)
for pin in list(SENSORS.values()) + [BUTTON_START, BUTTON_RESET]:
    lgpio.gpio_claim_input(h, pin, lgpio.SET_ACTIVE_LOW)

def led_reset_on():
    lgpio.gpio_write(h, LED_RESET, 0)

def led_reset_off():
    lgpio.gpio_write(h, LED_RESET, 1)

def alarm_on():
    lgpio.gpio_write(h, BUZZER, 0)

def alarm_off():
    lgpio.gpio_write(h, BUZZER, 1)

def start_btn_press():
    return bool(lgpio.gpio_read(h, BUTTON_START))

def reset_btn_press():
    return bool(lgpio.gpio_read(h, BUTTON_RESET))

try:
    while True:
        # lgpio.gpio_write(h, LED_RESET, 0)
        # time.sleep(1)
        # lgpio.gpio_write(h, LED_RESET, 1)
        # time.sleep(1)
        # lgpio.gpio_write(h, BUZZER, 0)
        # time.sleep(1)
        # lgpio.gpio_write(h, BUZZER, 1)
        # time.sleep(1)
        print("start",start_btn_press())
        
        print("reset",reset_btn_press())
        time.sleep(1)


except KeyboardInterrupt:
    print("\nStopping... turning everything OFF")

    # 🔴 Turn OFF all outputs before exit
    lgpio.gpio_write(h, LED_RESET, 1)
    lgpio.gpio_write(h, BUZZER, 1)

finally:
    lgpio.gpiochip_close(h)