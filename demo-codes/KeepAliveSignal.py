import time
import board
import digitalio

led = digitalio.DigitalInOut(board.LED)
led.direction = digitalio.Direction.OUTPUT

load44 = digitalio.DigitalInOut(board.GP2)
load44.direction = digitalio.Direction.OUTPUT

print("Zapnuti programu...")

# Proměnná pro sledování času (neblokující časovač)
last_hello_time = time.monotonic()

print("[INFO] Kontrolor: Systém spuštěn. ")

while True:
    led.value = True
    time.sleep(0.5)
    led.value = False
    time.sleep(0.4)
         
    current_time = time.monotonic()

    # 2. Keep alive signal (každých 15 sekund)
    if current_time - last_hello_time >= 15:
        load44.value = True
        led.value = True
        time.sleep(1) # 1 sekundu se zatezuje. 
        load44.value = False
        led.value = False
        last_hello_time = current_time