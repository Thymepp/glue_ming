import lgpio
import time

h = lgpio.gpiochip_open(0)  # open GPIO chip

LED = 17  # GPIO17 (pin 11)

lgpio.gpio_claim_output(h, LED)

lgpio.gpio_write(h, LED, 1)  # ON
time.sleep(1)
lgpio.gpio_write(h, LED, 0)  # OFF

lgpio.gpiochip_close(h)