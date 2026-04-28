import time
import board
import digitalio
import neopixel

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT
print("Loop starting!")
for i in range(10):
    print("Loop number", i)
print("Loop finished!")

n_pixels = 12
led_n = neopixel.NeoPixel(board.GP0, n_pixels)
led_n.brightness = 0.1

while True:
    led.value = True
    time.sleep(0.5)
    led.value = False
    time.sleep(0.1)
    print("BLIK")
    for i in range(n_pixels):
        led_n[i] = (255, 0, 0)
    time.sleep(0.5)
    for i in range(n_pixels):
        led_n[i] = (0, 255, 0)
    time.sleep(0.5)
    for i in range(n_pixels):
        led_n[i] = (0, 0, 255)
    time.sleep(0.5)
    # vypni vsechny ledky
    for i in range(n_pixels):
        led_n[i] = (0, 0, 0)
    # auticko
    for i in range(n_pixels):
        led_n[i] = (200, 200, 200)
        time.sleep(0.5)
        led_n[i] = (00, 00, 00)
        
    for i in range(n_pixels):
        led_n[i] = (0, 0, 0)