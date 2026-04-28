import time
import board
import digitalio
import neopixel

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

load44 = digitalio.DigitalInOut(board.GP2)
load44.direction = digitalio.Direction.OUTPUT

print("Zapnuti programu...")

n_pixels = 12
led_n = neopixel.NeoPixel(board.GP0, n_pixels)
led_n.brightness = 0.1

# Proměnná pro sledování času (neblokující časovač)
last_hello_time = time.monotonic()

print("[INFO] Kontrolor: Systém spuštěn. Čekám na vstup...")

while True:
    led.value = True
    time.sleep(0.5)
    led.value = False
    time.sleep(0.1)
         
    current_time = time.monotonic()

    # 2. Logika periodického hlášení (každých 60 sekund)
    if current_time - last_hello_time >= 15:
        print("zatezuji...")
        buffer = led_n.brightness
        for i in range(n_pixels):
            led_n[i] = (255,255,255)
        led_n.brightness = 1  
        load44.value = True
        led.value = True
        time.sleep(1)
        for i in range(n_pixels):
            led_n[i] = (0, 0, 0) 
        led_n.brightness = buffer
        load44.value = False
        led.value = False
        last_hello_time = current_time