"""
EdyKostka - bring-up nastroj pro identifikaci LED a vstupu.

Pouziti pres serial (REPL) - prikazy reaguji okamzite, BEZ Enteru:
  0..9     toggle LED na GPIO 0..9
  a..f     toggle LED na GPIO 10..15  (hex)
  A        vsechny LED ON       (uppercase A)
  Z        vsechny LED OFF      (uppercase Z)
  S        vypis stav LED       (uppercase S)
  W        zapnout keep-alive signal
  Woff     vypnout keep-alive signal
  ?        help

Vstupy GPIO 18..22 se sleduji automaticky a kazda zmena se vypise.
Keep-alive: perioda 10 s, pulz HIGH 400 ms, zbytek LOW. Po bootu vypnuto.
"""

import board
import digitalio
import supervisor
import sys
import time

# --- nejdrive pockame na pripojeni seriaku, at uzivatel uvidi i prvni vypisy ---
# (CircuitPython prvni vypisy jinak zahodi, kdyz host jeste neotevrel COM port)
_t0 = time.monotonic()
while not supervisor.runtime.serial_connected:
    if time.monotonic() - _t0 > 3.0:
        break  # po 3 s pojedeme dal i bez seriaku
    time.sleep(0.05)

print()
print("=" * 50)
print("[BOOT] EdyKostka start")
print("[BOOT] CircuitPython bezi, seriak pripojen.")
print("=" * 50)

print("[BOOT] import knihoven...")
import neopixel  # noqa: E402
print("[BOOT] import OK (board, digitalio, neopixel, supervisor, sys, time)")

LED_PINS = list(range(16))            # GPIO 0..15
INVERTED_LEDS = {3, 4, 7, 8, 12}      # HIGH = OFF
INPUT_PINS = [18, 19, 20, 21, 22]
KEEP_ALIVE_PIN = 16
ONEWIRE_PIN = 17
N_ONEWIRE_PIXELS = 12
KA_SWITCH_PIN = 21          # SWITCH 5 (RED, OFF-ON) - rizeni keep-alive
SW1_JERAB_PIN = 18          # SWITCH 1 (YELLOW, OFF-ON) - rozsvitit jerab
SW2_SEMAFOR_PIN = 19        # SWITCH 2 (YELLOW, OFF-ON) - sekvence semaforu
SW4_ALL_PIN = 20            # SWITCH 4 (GREEN, OFF-(ON)) - vsechny LED jako 'A'

# GPIO LED pro skupiny pouzite ve spinacove logice
JERAB_PINS = (14, 15, 10, 0, 9, 13, 1)
JERAB_NONEXCLUSIVE = tuple(n for n in JERAB_PINS if n not in (0, 1))
SEMAFOR_SEQUENCE = (3, 2, 4)  # RED -> YELLOW -> GREEN
SEMAFOR_STEP_S = 0.4

DEBOUNCE_S = 0.03
KA_PERIOD_S = 10.0
KA_PULSE_S = 0.4

# GPIO 0 (RED*) a GPIO 1 (YELLOW*) v JERAB-TOP nemohou svitit zaroven.
# Pri prikazu "A" budou alternovat s touto periodou.
EXCLUSIVE_PAIR = (0, 1)
ALT_PERIOD_S = 1.0

# Logicke skupiny LED dle zadani (poradi = poradi probliknuti pri bootu).
# V ramci skupiny: od BOT nahoru, zprava doleva (dle sloupce 'place' v zadani).
LED_GROUPS = (
    ("POZOR",    (5, 6)),                       # GPIO poradi dle zadani
    ("SEMAFOR",  (4, 2, 3)),                    # BOT(GREEN), MID(YELLOW), TOP(RED)
    ("MICHACKA", (8,)),                         # FRONT
    ("STAVBA",   (12,)),                        # TOP
    ("JERAB",    (14, 15, 10, 0, 9, 13, 1)),    # BOT, MID, CABIN, TOP-RED, RIGHT, LEFT, TOP-YELLOW
    ("BULDOZER", (7,)),                         # TOP
    ("SWITCH",   (11,)),
)

HEX_DIGITS = "0123456789abcdef"


def gp(n):
    return getattr(board, "GP{}".format(n))


# --- LED setup ---
print("[INIT] konfigurace 16 LED na GPIO 0..15...")
leds = {}
led_on = {}
for n in LED_PINS:
    pin = digitalio.DigitalInOut(gp(n))
    pin.direction = digitalio.Direction.OUTPUT
    leds[n] = pin
    led_on[n] = False
print("[INIT]   LED nakonfigurovany. Invertovane (HIGH=OFF): {}".format(sorted(INVERTED_LEDS)))


def set_led(n, on):
    led_on[n] = on
    if n in INVERTED_LEDS:
        leds[n].value = not on
    else:
        leds[n].value = on


for n in LED_PINS:
    set_led(n, False)


# --- Keep-alive setup (GP16) ---
print("[INIT] konfigurace keep-alive pinu na GPIO {} (LOW, vypnuto)...".format(KEEP_ALIVE_PIN))
ka_pin = digitalio.DigitalInOut(gp(KEEP_ALIVE_PIN))
ka_pin.direction = digitalio.Direction.OUTPUT
ka_pin.value = False
ka_enabled = False
ka_period_start = 0.0
ka_high_now = False
print("[INIT]   keep-alive pripraven (po bootu vypnuto).")


def keep_alive_tick(t):
    """Neblokujici keep-alive: kazdych 10 s pulz 400 ms HIGH."""
    global ka_period_start, ka_high_now
    if not ka_enabled:
        if ka_high_now:
            ka_pin.value = False
            ka_high_now = False
        return
    dt = t - ka_period_start
    if dt >= KA_PERIOD_S:
        ka_period_start = t
        dt = 0.0
    if dt < KA_PULSE_S:
        if not ka_high_now:
            ka_pin.value = True
            ka_high_now = True
    else:
        if ka_high_now:
            ka_pin.value = False
            ka_high_now = False


def keep_alive_on():
    global ka_enabled, ka_period_start, ka_high_now
    if ka_enabled:
        print("[KA] uz je zapnuto")
        return
    ka_enabled = True
    ka_period_start = time.monotonic()
    ka_high_now = False
    print("[KA] keep-alive ZAPNUTO (perioda 10 s, pulz 400 ms)")


def keep_alive_off():
    global ka_enabled, ka_high_now
    if not ka_enabled:
        print("[KA] uz je vypnuto")
        return
    ka_enabled = False
    ka_pin.value = False
    ka_high_now = False
    print("[KA] keep-alive VYPNUTO")


# --- Alternovani GPIO 0 / GPIO 1 (exkluzivni dvojice) ---
alt_mode = False
alt_start = 0.0


def alt_start_now():
    """Spusti alternovani exkluzivni dvojice. GPIO 0 zacne svitit."""
    global alt_mode, alt_start
    alt_mode = True
    alt_start = time.monotonic()
    set_led(EXCLUSIVE_PAIR[0], True)
    set_led(EXCLUSIVE_PAIR[1], False)


def alt_stop():
    global alt_mode
    if alt_mode:
        alt_mode = False


def alt_tick(t):
    """Stridani GPIO 0/1 s periodou ALT_PERIOD_S (0.5 s kazdy)."""
    if not alt_mode:
        return
    phase = (t - alt_start) % ALT_PERIOD_S
    want_first = phase < (ALT_PERIOD_S / 2.0)
    a, b = EXCLUSIVE_PAIR
    if want_first:
        if not led_on[a]:
            set_led(a, True)
        if led_on[b]:
            set_led(b, False)
    else:
        if led_on[a]:
            set_led(a, False)
        if not led_on[b]:
            set_led(b, True)


# --- JERAB (SWITCH 1) ---
def jerab_on():
    for n in JERAB_NONEXCLUSIVE:
        set_led(n, True)
    alt_start_now()  # GPIO 0 a 1 alternuji (nesmi svitit zaroven)
    print("[JERAB] zapnuto (GPIO 0/1 alternuji)")


def jerab_off():
    alt_stop()
    for n in JERAB_PINS:
        set_led(n, False)
    print("[JERAB] vypnuto")


# --- SEMAFOR (SWITCH 2) ---
# Neblokujici sekvence: po stisku se LED rozsvecuji jedna po druhe s krokem
# SEMAFOR_STEP_S, na konci sviti vsechny tri. Po uvolneni vse zhasne.
sem_active = False
sem_step = 0
sem_last_step_t = 0.0


def semafor_start():
    global sem_active, sem_step, sem_last_step_t
    sem_active = True
    sem_step = 1
    sem_last_step_t = time.monotonic()
    set_led(SEMAFOR_SEQUENCE[0], True)
    print("[SEMAFOR] sekvence START: GPIO {} ON".format(SEMAFOR_SEQUENCE[0]))


def semafor_off():
    global sem_active, sem_step
    sem_active = False
    sem_step = 0
    for n in SEMAFOR_SEQUENCE:
        set_led(n, False)
    print("[SEMAFOR] zhasnuto")


def semafor_tick(t):
    global sem_step, sem_last_step_t
    if not sem_active or sem_step >= len(SEMAFOR_SEQUENCE):
        return
    if (t - sem_last_step_t) >= SEMAFOR_STEP_S:
        n = SEMAFOR_SEQUENCE[sem_step]
        set_led(n, True)
        print("[SEMAFOR] krok {}: GPIO {} ON".format(sem_step + 1, n))
        sem_step += 1
        sem_last_step_t = t


# --- Vsechny LED ON/OFF (sdileno mezi 'A'/'Z' a SWITCH 4) ---
def all_leds_on():
    for n in LED_PINS:
        if n in EXCLUSIVE_PAIR:
            continue  # tyhle ridi alt_tick
        set_led(n, True)
    alt_start_now()
    print("[LED] vsechny ON (GPIO {}/{} alternuji s periodou {:.1f} s)".format(
        EXCLUSIVE_PAIR[0], EXCLUSIVE_PAIR[1], ALT_PERIOD_S))


def all_leds_off():
    alt_stop()
    for n in LED_PINS:
        set_led(n, False)
    print("[LED] vsechny OFF")


# --- 1-wire LED setup (GP17, 12x WS2812) ---
print("[INIT] inicializace 1-wire LED ({}x WS2812 na GPIO {})...".format(N_ONEWIRE_PIXELS, ONEWIRE_PIN))
onewire = neopixel.NeoPixel(gp(ONEWIRE_PIN), N_ONEWIRE_PIXELS, brightness=0.2, auto_write=False)
onewire.fill((0, 0, 0))
onewire.show()
print("[INIT]   1-wire LED zhasnuty.")


# --- Init test: probliknuti LED po skupinach, v ramci skupiny LED po LED ---
LED_TEST_ON_S = 0.4

print("[INIT] Test LED po skupinach (LED po LED)...")
time.sleep(0.5)  # kratka pauza, at je videt cisty start
for name, pins in LED_GROUPS:
    print("[INIT]   skupina {:8s} -> GPIO {}".format(name, list(pins)))
    for n in pins:
        set_led(n, True)
        time.sleep(LED_TEST_ON_S)
        set_led(n, False)
print("[INIT] Test LED hotov - vsechny LED OFF.")

print("[INIT] Test 1-wire LED (zelena, pixel po pixelu)...")
for i in range(N_ONEWIRE_PIXELS):
    onewire[i] = (0, 255, 0)
    onewire.show()
    time.sleep(0.15)
onewire.fill((0, 0, 0))
onewire.show()
print("[INIT] Test 1-wire LED hotov.")


# --- Input setup ---
print("[INIT] konfigurace vstupu GPIO {} (Pull-UP, aktivni LOW)...".format(INPUT_PINS))
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
print("[INIT]   vstupy pripraveny. Aktualni stav: {}".format(
    {n: ("HIGH" if confirmed[n] else "LOW") for n in INPUT_PINS}))

# Po inicializaci srovnej keep-alive podle fyzicke polohy SWITCH 5 (GPIO 21).
# Aktivni LOW: LOW = sepnuto = KA zapnuto, HIGH = vypnuto = KA vypnuto.
if confirmed[KA_SWITCH_PIN] is False:
    print("[INIT]   SWITCH 5 sepnut -> zapinam keep-alive")
    keep_alive_on()
else:
    print("[INIT]   SWITCH 5 vypnut -> keep-alive zustava vypnuty")

if confirmed[SW1_JERAB_PIN] is False:
    print("[INIT]   SWITCH 1 sepnut -> zapinam JERAB")
    jerab_on()
if confirmed[SW2_SEMAFOR_PIN] is False:
    print("[INIT]   SWITCH 2 sepnut -> spoustim sekvenci SEMAFOR")
    semafor_start()
if confirmed[SW4_ALL_PIN] is False:
    print("[INIT]   SWITCH 4 drzen -> zapinam vsechny LED")
    all_leds_on()


def print_help():
    print("-" * 50)
    print("Prikazy (jednim znakem, bez Enteru):")
    print("  0..9 a..f  -> toggle LED GPIO 0..15 (hex)")
    print("  A          -> vsechny LED ON (GPIO 0/1 alternuji 1 s)")
    print("  Z          -> vsechny LED OFF")
    print("  S          -> stav LED (vypis svitici)")
    print("  W          -> zapnout keep-alive signal")
    print("  Woff       -> vypnout keep-alive signal")
    print("  ?          -> tato napoveda")
    print("Vstupy GPIO 18..22 se sleduji a tisknou automaticky.")
    print("-" * 50)


def handle_token(tok):
    """Obslouzi 1- nebo viceznakovy token (Woff)."""
    if tok == "":
        return
    if len(tok) == 1:
        ch = tok
        if ch in HEX_DIGITS:
            n = int(ch, 16)
            if n in EXCLUSIVE_PAIR and alt_mode:
                alt_stop()
                print("[LED] alternovani GPIO {}/{} ukonceno (manualni toggle)".format(*EXCLUSIVE_PAIR))
            set_led(n, not led_on[n])
            print("[LED] GPIO {:2d} = {}".format(n, "ON " if led_on[n] else "OFF"))
            return
        if ch == "A":
            all_leds_on()
            return
        if ch == "Z":
            all_leds_off()
            return
        if ch == "S":
            svici = [n for n in LED_PINS if led_on[n]]
            print("[LED] svici GPIO: {}".format(svici))
            return
        if ch == "?":
            print_help()
            return
        if ch == "W":
            keep_alive_on()
            return
        print("[!] neznamy znak: {!r}  (? = napoveda)".format(ch))
        return
    if tok == "Woff":
        keep_alive_off()
        return
    print("[!] neznamy prikaz: {!r}  (? = napoveda)".format(tok))


# Stav pro vstupni parser - kvuli viceznakovemu "Woff"
input_buffer = ""
last_char_t = 0.0
W_TIMEOUT_S = 0.25  # po teto dobe se osamocene "W" vyhodnoti jako zapnuti KA


def feed_char(ch, t):
    """Akumuluje znaky a vyhodnocuje. Whitespace = oddelovac/flush."""
    global input_buffer
    if ch in ("\r", "\n", " ", "\t"):
        if input_buffer:
            handle_token(input_buffer)
            input_buffer = ""
        return
    if input_buffer:
        input_buffer += ch
        if len(input_buffer) >= 4:  # max "Woff"
            handle_token(input_buffer)
            input_buffer = ""
        return
    if ch == "W":
        # Pockame, jestli prijde "off"
        input_buffer = ch
        return
    handle_token(ch)


print("=" * 50)
print("EdyKostka bring-up")
print("=" * 50)
print_help()

while True:
    t = time.monotonic()

    if supervisor.runtime.serial_bytes_available:
        ch = sys.stdin.read(1)
        feed_char(ch, t)
        last_char_t = t
    else:
        # Osamocene "W" bez pokracovani -> po timeoutu zapni keep-alive
        if input_buffer == "W" and (t - last_char_t) > W_TIMEOUT_S:
            handle_token(input_buffer)
            input_buffer = ""

    for n in INPUT_PINS:
        v = inputs[n].value
        if v != raw_state[n]:
            raw_state[n] = v
            raw_changed_at[n] = t
        elif v != confirmed[n] and (t - raw_changed_at[n]) > DEBOUNCE_S:
            confirmed[n] = v
            event = "STISK" if v is False else "uvolneno"
            print("[VSTUP] GPIO {} -> {}".format(n, event))
            if n == KA_SWITCH_PIN:
                if v is False:
                    keep_alive_on()
                else:
                    keep_alive_off()
            elif n == SW1_JERAB_PIN:
                if v is False:
                    jerab_on()
                else:
                    jerab_off()
            elif n == SW2_SEMAFOR_PIN:
                if v is False:
                    semafor_start()
                else:
                    semafor_off()
            elif n == SW4_ALL_PIN:
                if v is False:
                    all_leds_on()
                else:
                    all_leds_off()

    keep_alive_tick(t)
    alt_tick(t)
    semafor_tick(t)

    time.sleep(0.005)
