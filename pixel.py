"""
pixel.py - samostatny test 1-wire LED retezce (Inolux IN-PI55, WS2812-kompatibilni).

Inspirovano demo-codes/Neopixel_demoPrusa.py.
Pouziva pouze NeoPixel na GP17 (dle HW EdyKostky) a onboard LED jako "heartbeat".
"""

import time
import board
import digitalio
import neopixel

ONEWIRE_PIN = board.GP17
N_PIXELS = 12

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

print("Pixel test starting!")
for i in range(5):
    print("Loop number", i)
print("Init finished, vstupuji do hlavni smycky.")

pixels = neopixel.NeoPixel(ONEWIRE_PIN, N_PIXELS, brightness=0.2, auto_write=False)
pixels.fill((0, 0, 0))
pixels.show()

while True:
    # heartbeat na onboard LED
    led.value = True
    time.sleep(0.5)
    led.value = False
    time.sleep(0.1)
    print("BLIK")

    # cely retez cervene
    pixels.fill((255, 0, 0))
    pixels.show()
    time.sleep(0.5)

    # cely retez zelene
    pixels.fill((0, 255, 0))
    pixels.show()
    time.sleep(0.5)

    # cely retez modre
    pixels.fill((0, 0, 255))
    pixels.show()
    time.sleep(0.5)

    # zhasnout
    pixels.fill((0, 0, 0))
    pixels.show()

    # auticko - jeden pohybujici se bily pixel
    for i in range(N_PIXELS):
        pixels[i] = (200, 200, 200)
        pixels.show()
        time.sleep(0.2)
        pixels[i] = (0, 0, 0)
        pixels.show()

    pixels.fill((0, 0, 0))
    pixels.show()
