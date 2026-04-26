"""
EdyKostka - bring-up nastroj pro identifikaci LED a vstupu.

Pouziti pres serial (REPL) - prikazy reaguji okamzite, BEZ Enteru:
  0..9     toggle LED na GPIO 0..9
  a..f     toggle LED na GPIO 10..15  (hex)
  A        vsechny LED ON       (uppercase A)
  Z        vsechny LED OFF      (uppercase Z)
  S        vypis stav LED       (uppercase S)
  ?        help

Vstupy GPIO 18..22 se sleduji automaticky a kazda zmena se vypise.
"""

import board
import digitalio
import supervisor
import sys
import time

LED_PINS = list(range(16))            # GPIO 0..15
INVERTED_LEDS = {3, 4, 7, 8, 11, 12}  # HIGH = OFF
INPUT_PINS = [18, 19, 20, 21, 22]
DEBOUNCE_S = 0.03

HEX_DIGITS = "0123456789abcdef"


def gp(n):
    return getattr(board, "GP{}".format(n))


# --- LED setup ---
leds = {}
led_on = {}
for n in LED_PINS:
    pin = digitalio.DigitalInOut(gp(n))
    pin.direction = digitalio.Direction.OUTPUT
    leds[n] = pin
    led_on[n] = False


def set_led(n, on):
    led_on[n] = on
    if n in INVERTED_LEDS:
        leds[n].value = not on
    else:
        leds[n].value = on


for n in LED_PINS:
    set_led(n, False)

# --- Input setup ---
inputs = {}
raw_state = {}
raw_changed_at = {}
confirmed = {}
for n in INPUT_PINS:
    pin = digitalio.DigitalInOut(gp(n))
    pin.direction = digitalio.Direction.INPUT
    pin.pull = digitalio.Pull.UP
    inputs[n] = pin
    v = pin.value
    raw_state[n] = v
    raw_changed_at[n] = 0.0
    confirmed[n] = v


def print_help():
    print("-" * 50)
    print("Prikazy (jednim znakem, bez Enteru):")
    print("  0..9 a..f  -> toggle LED GPIO 0..15 (hex)")
    print("  A          -> vsechny LED ON")
    print("  Z          -> vsechny LED OFF")
    print("  S          -> stav LED (vypis svitici)")
    print("  ?          -> tato napoveda")
    print("Vstupy GPIO 18..22 se sleduji a tisknou automaticky.")
    print("-" * 50)


def handle_char(ch):
    if ch in ("\r", "\n", " ", "\t"):
        return  # ignoruj whitespace
    if ch in HEX_DIGITS:
        n = int(ch, 16)
        set_led(n, not led_on[n])
        print("[LED] GPIO {:2d} = {}".format(n, "ON " if led_on[n] else "OFF"))
        return
    if ch == "A":
        for n in LED_PINS:
            set_led(n, True)
        print("[LED] vsechny ON")
        return
    if ch == "Z":
        for n in LED_PINS:
            set_led(n, False)
        print("[LED] vsechny OFF")
        return
    if ch == "S":
        svici = [n for n in LED_PINS if led_on[n]]
        print("[LED] svici GPIO: {}".format(svici))
        return
    if ch == "?":
        print_help()
        return
    print("[!] neznamy znak: {!r}  (? = napoveda)".format(ch))


print("=" * 50)
print("EdyKostka bring-up")
print("=" * 50)
print_help()

while True:
    if supervisor.runtime.serial_bytes_available:
        ch = sys.stdin.read(1)
        handle_char(ch)

    t = time.monotonic()
    for n in INPUT_PINS:
        v = inputs[n].value
        if v != raw_state[n]:
            raw_state[n] = v
            raw_changed_at[n] = t
        elif v != confirmed[n] and (t - raw_changed_at[n]) > DEBOUNCE_S:
            confirmed[n] = v
            event = "STISK" if v is False else "uvolneno"
            print("[VSTUP] GPIO {} -> {}".format(n, event))

    time.sleep(0.005)
