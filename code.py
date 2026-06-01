"""
EdyKostka - hlavni program.

Strukturovano podle zadani:
  * 16 PWM LED (GPIO 0..15) s individualni duty, sdilenou frekvenci
  * PWM hodnoty persistovane v microcontroller.nvm
  * 1-wire LED (12x WS2812 / Inolux IN-PI55) na GP17
  * Keep-alive na GP16 (perioda 10 s, pulz 400 ms) - bezi v pozadi od bootu
  * Onboard LED zrcadli stav keep-alive (DEBUG)
  * 5 vstupu (GP18..22) - debounced, mapovany na HRA funkce
  * REPL pres serial - prikazy potvrzovane Enterem, echo, Backspace
  * HRA funkce: PozorStavba (auto), vabeniKoristi, MajakBuldozer,
                RozsvitJerab, RozsvitStavbu, PustAuto (SEMAFOR)
  * sleepBox + ShutDown casovace

REPL napoveda - viz prikaz '?'.
"""

import board
import digitalio
import pwmio
import supervisor
import sys
import time
import math
import microcontroller
import neopixel

# ====================================================================
# KONSTANTY
# ====================================================================
LED_PINS = list(range(16))
INVERTED_LEDS = {3, 4, 7, 8, 12}        # HIGH = OFF
INPUT_PINS = [18, 19, 20, 21, 22]
KEEP_ALIVE_PIN = 16
ONEWIRE_PIN = 17
N_ONEWIRE_PIXELS = 12
BUZZER_PIN = 28                          # jen digital out - test pip

# Mapovani SWITCH -> GPIO (numerace dle zadani)
SW1_PIN = 18  # YELLOW  OFF-ON  -> MajakBuldozer
SW2_PIN = 19  # YELLOW  OFF-ON  -> RozsvitJerab
SW3_PIN = 22  # GREY    OFF-ON  -> RozsvitStavbu
SW4_PIN = 20  # GREEN   OFF-(ON) tlacitko -> PustAuto (dobehne)
SW5_PIN = 21  # RED     OFF-ON  -> vsechny LED ON (drzi)

# PWM defaults per LED z LED-Table
PWM_FREQ_DEFAULT = 500
PWM_FREQ_MIN = 1
PWM_FREQ_MAX = 200000
PWM_MAX_PCT = {
    0: 8,    1: 20,   2: 100,  3: 100,
    4: 100,  5: 100,  6: 100,  7: 40,
    8: 100,  9: 100, 10: 100, 11: 100,
   12: 40,  13: 100, 14: 100, 15: 100,
}

EXCLUSIVE_PAIR = (0, 1)
ALT_PERIOD_S = 1.0

# LED-Table odvozene skupiny
LED_GROUPS_INIT = (
    ("POZOR",    (5, 6)),
    ("SEMAFOR",  (4, 2, 3)),
    ("MICHACKA", (8,)),
    ("STAVBA",   (12,)),
    ("JERAB",    (14, 15, 10, 0, 9, 13, 1)),
    ("BULDOZER", (7,)),
    ("TLACITKO", (11,)),
)
JERAB_PINS = (14, 15, 10, 0, 9, 13, 1)
JERAB_PINS_NO_YELLOW = (14, 15, 10, 0, 9, 13)   # bez GPIO 1 (yellow)
JERAB_YELLOW = 1
SEMAFOR_RED, SEMAFOR_YELLOW, SEMAFOR_GREEN = 3, 2, 4
POZOR_PINS = (5, 6)
TLACITKO_PIN = 11
BULDOZER_PIN = 7
STAVBA_PIN = 12
MICHACKA_PIN = 8

HEX_DIGITS = "0123456789abcdef"

# Casove konstanty (viz zadani: Tabulka s konstantami)
LED_TEST_ON_S = 0.15
SLEEP_BOX_TIMEOUT_S = 600.0
SHUTDOWN_TIMEOUT_S = 600.0
JERAB_INIT_DELAY_MS = 100
VABENI_BOOT_DELAY_S = 5.0
KA_PERIOD_S = 10.0
KA_PULSE_S = 0.4
DEBOUNCE_S = 0.03

# HRA - tunable
POZOR_BLINK_S = 0.5            # POZOR LED 5/6 blikani period (half-period)
VABENI_BPM = 15                # vabeniKoristi - tepu za minutu (pomale buseni srdce)
VABENI_PERIOD_S = 60.0 / VABENI_BPM   # delka jednoho tepu v sekundach
VABENI_DARK_S = 0.300          # ztmavena cast mezi tepy (max 300 ms)
VABENI_GAMMA = 2.2             # gamma korekce - oko vnima jas nelinearne
MAJAK_PERIOD_S = 2.0           # MajakBuldozer perioda - jeden prulet majaku
MAJAK_SHAPE_POW = 4            # sin^N - vetsi N = uzsi peak (vic "maják")
STAVBA_FADE_IN_S = 2.5         # sodikova vybojka - doba nabihani
STAVBA_FADE_OUT_S = 2.5        # zrcadlove fade-out (vypinani)
JERAB_YELLOW_START_DELAY_S = 4.0
JERAB_YELLOW_ON_S = 0.3        # 300 ms
JERAB_RED_ON_S = 3.0           # 3 s
# SEMAFOR - PustAuto
SEM_INIT_HOLD_S = 3.0
SEM_RUN_RED_TO_YELLOW_S = 2.5  # cervena dosviti
SEM_RUN_YELLOW_S = 1.2         # zluta
SEM_RUN_GREEN_HOLD_S = 1.0     # pak prejde GO
SEM_GO_TO_ODJETO_S = 3.0
SEM_ODJETO_GREEN_HOLD_S = 1.0
SEM_ODJETO_YELLOW_S = 1.2
SEM_ODJETO_TO_END_S = 3.0      # uvedeno v zadani jako prodleva ODJETO->END

# NVM layout
NVM_MAGIC = 0xA5
NVM_VERSION = 0x01
NVM_SIZE = 20  # 0:magic 1:ver 2-3:freq 4-19:duty per LED

# OneWire
ONEWIRE_BRIGHTNESS = 0.06


# ====================================================================
# BOOT: pockame na serial (max 3 s)
# ====================================================================
_t0 = time.monotonic()
while not supervisor.runtime.serial_connected:
    if time.monotonic() - _t0 > 3.0:
        break
    time.sleep(0.05)

print()
print("=" * 50)
print("[BOOT] EdyKostka start")
print("[BOOT] CircuitPython bezi, seriak pripojen.")
print("=" * 50)


def gp(n):
    return getattr(board, "GP{}".format(n))


# ====================================================================
# NVM - load/save PWM state
# ====================================================================
def nvm_defaults():
    """Defaults z LED-Table: PWM_MAX_PCT pro kazdou LED, freq=500."""
    duty = [PWM_MAX_PCT[n] for n in LED_PINS]
    return PWM_FREQ_DEFAULT, duty


def nvm_load():
    """Vrati (freq, duty[16]). Pri nevalidni NVM zapise a vrati defaults."""
    try:
        buf = bytes(microcontroller.nvm[0:NVM_SIZE])
    except Exception as e:
        print("[NVM] cteni selhalo ({}), pouziji defaults".format(e))
        f, d = nvm_defaults()
        return f, d
    if buf[0] != NVM_MAGIC or buf[1] != NVM_VERSION:
        print("[NVM] magic/verze chybi (0x{:02X}/0x{:02X}) -> zapis defaults".format(buf[0], buf[1]))
        f, d = nvm_defaults()
        nvm_save(f, d)
        return f, d
    freq = buf[2] | (buf[3] << 8)
    duty = [buf[4 + n] for n in LED_PINS]
    # Clamp na PWM_MAX_PCT - kdyby v NVM byla starsi vyssi hodnota
    duty = [min(duty[n], PWM_MAX_PCT[n]) for n in LED_PINS]
    if freq < PWM_FREQ_MIN or freq > PWM_FREQ_MAX:
        freq = PWM_FREQ_DEFAULT
    print("[NVM] nactena konfigurace: freq={} Hz, duty={}".format(freq, duty))
    return freq, duty


def nvm_save(freq, duty):
    buf = bytearray(NVM_SIZE)
    buf[0] = NVM_MAGIC
    buf[1] = NVM_VERSION
    buf[2] = freq & 0xFF
    buf[3] = (freq >> 8) & 0xFF
    for n in LED_PINS:
        v = duty[n]
        if v < 0:
            v = 0
        if v > 100:
            v = 100
        buf[4 + n] = v
    try:
        microcontroller.nvm[0:NVM_SIZE] = bytes(buf)
    except Exception as e:
        print("[NVM] zapis selhal: {}".format(e))


# ====================================================================
# PWM LED
# ====================================================================
pwm_freq, led_duty_pct = nvm_load()
led_on = {n: False for n in LED_PINS}
leds = {}

print("[INIT] PWM LED na GPIO 0..15, freq={} Hz, invertovane (HIGH=OFF): {}".format(
    pwm_freq, sorted(INVERTED_LEDS)))


def apply_led(n):
    """Zapis duty_cycle na hardware podle led_on[n] a led_duty_pct[n]."""
    pct = led_duty_pct[n] if led_on[n] else 0
    raw = int(65535 * pct / 100)
    if n in INVERTED_LEDS:
        raw = 65535 - raw
    leds[n].duty_cycle = raw


def apply_led_with_duty(n, pct):
    """Aplikuj LED s konkretnim duty (pro PWM animace - vabeniKoristi, MajakBuldozer)."""
    # Clamp na PWM_MAX_PCT[n]
    if pct > PWM_MAX_PCT[n]:
        pct = PWM_MAX_PCT[n]
    if pct < 0:
        pct = 0
    raw = int(65535 * pct / 100)
    if n in INVERTED_LEDS:
        raw = 65535 - raw
    leds[n].duty_cycle = raw


for n in LED_PINS:
    pwm = pwmio.PWMOut(gp(n), frequency=pwm_freq, duty_cycle=0, variable_frequency=False)
    leds[n] = pwm
    apply_led(n)


def set_led(n, on):
    led_on[n] = on
    apply_led(n)


def reapply_all_leds():
    for n in LED_PINS:
        apply_led(n)


def set_led_duty(n, pct):
    """Nastav duty 0..100 % pro jednu LED + clamp na MAX + zapnout."""
    if pct < 0:
        pct = 0
    if pct > PWM_MAX_PCT[n]:
        pct = PWM_MAX_PCT[n]
    led_duty_pct[n] = pct
    led_on[n] = True
    apply_led(n)
    nvm_save(pwm_freq, led_duty_pct)
    print("[PWM] GPIO {:2d} duty={}% (MAX={}%) -> ON".format(n, pct, PWM_MAX_PCT[n]))


def set_all_duty(pct):
    """Nastav duty pro vsechny LED, clamped na PWM_MAX_PCT kazde LED."""
    for n in LED_PINS:
        v = min(pct, PWM_MAX_PCT[n])
        if v < 0:
            v = 0
        led_duty_pct[n] = v
        apply_led(n)
    nvm_save(pwm_freq, led_duty_pct)
    print("[PWM] duty (clamped na MAX) -> {}".format(led_duty_pct))


def set_pwm_freq(hz):
    global pwm_freq
    if hz < PWM_FREQ_MIN or hz > PWM_FREQ_MAX:
        print("[PWM] freq mimo rozsah {}..{} Hz".format(PWM_FREQ_MIN, PWM_FREQ_MAX))
        return
    pwm_freq = hz
    for n in LED_PINS:
        leds[n].deinit()
    for n in LED_PINS:
        leds[n] = pwmio.PWMOut(gp(n), frequency=pwm_freq, duty_cycle=0, variable_frequency=False)
        apply_led(n)
    nvm_save(pwm_freq, led_duty_pct)
    print("[PWM] frequency = {} Hz".format(pwm_freq))


def factory_reset():
    global pwm_freq
    f, d = nvm_defaults()
    pwm_freq = f
    for n in LED_PINS:
        led_duty_pct[n] = d[n]
    for n in LED_PINS:
        leds[n].deinit()
    for n in LED_PINS:
        leds[n] = pwmio.PWMOut(gp(n), frequency=pwm_freq, duty_cycle=0, variable_frequency=False)
        led_on[n] = False
        apply_led(n)
    nvm_save(pwm_freq, led_duty_pct)
    print("[PWM] FactoryRESET hotovo. freq={} Hz, duty=defaults z LED-Table".format(pwm_freq))


# ====================================================================
# Keep-alive (GP16) - bezi automaticky od bootu
# ====================================================================
print("[INIT] keep-alive na GPIO {} (perioda {}s, pulz {}ms)".format(
    KEEP_ALIVE_PIN, KA_PERIOD_S, int(KA_PULSE_S * 1000)))
ka_pin = digitalio.DigitalInOut(gp(KEEP_ALIVE_PIN))
ka_pin.direction = digitalio.Direction.OUTPUT
ka_pin.value = False
ka_enabled = True   # auto-on od bootu (zadani: "na pozadi bezi keep-a-live")
ka_period_start = time.monotonic()
ka_high_now = False

# Onboard LED jako mirror keep-alive (DEBUG sekce)
onboard = digitalio.DigitalInOut(board.LED)
onboard.direction = digitalio.Direction.OUTPUT
onboard.value = False
# DEBUG: prodlouzit puls onboard LED aspon na 1 s
DEBUG_KA_LED_MIN_S = 1.0
ka_led_off_at = 0.0
ka_led_on = False


def keep_alive_tick(t):
    global ka_period_start, ka_high_now, ka_led_off_at, ka_led_on
    if not ka_enabled:
        if ka_high_now:
            ka_pin.value = False
            ka_high_now = False
        # onboard LED dobehnuti
        if ka_led_on and t >= ka_led_off_at:
            onboard.value = False
            ka_led_on = False
        return
    dt = t - ka_period_start
    if dt >= KA_PERIOD_S:
        ka_period_start = t
        dt = 0.0
    if dt < KA_PULSE_S:
        if not ka_high_now:
            ka_pin.value = True
            ka_high_now = True
            # DEBUG: rozsvit onboard, drz aspon DEBUG_KA_LED_MIN_S
            onboard.value = True
            ka_led_on = True
            ka_led_off_at = t + max(DEBUG_KA_LED_MIN_S, KA_PULSE_S)
    else:
        if ka_high_now:
            ka_pin.value = False
            ka_high_now = False
    # onboard LED dobehnuti po skonceni pulzu
    if ka_led_on and t >= ka_led_off_at:
        onboard.value = False
        ka_led_on = False


def keep_alive_on():
    global ka_enabled, ka_period_start, ka_high_now
    if ka_enabled:
        print("[KA] uz je zapnuto")
        return
    ka_enabled = True
    ka_period_start = time.monotonic()
    ka_high_now = False
    print("[KA] keep-alive ZAPNUTO")


def keep_alive_off():
    global ka_enabled, ka_high_now
    if not ka_enabled:
        print("[KA] uz je vypnuto")
        return
    ka_enabled = False
    ka_pin.value = False
    ka_high_now = False
    onboard.value = False
    print("[KA] keep-alive VYPNUTO")


# ====================================================================
# 1-wire LED (GP17)
# ====================================================================
print("[INIT] 1-wire LED ({}x WS2812/Inolux na GPIO {}, brightness={})".format(
    N_ONEWIRE_PIXELS, ONEWIRE_PIN, ONEWIRE_BRIGHTNESS))
onewire = neopixel.NeoPixel(
    gp(ONEWIRE_PIN), N_ONEWIRE_PIXELS,
    brightness=ONEWIRE_BRIGHTNESS, auto_write=False, pixel_order=neopixel.GRB,
)
onewire.fill((0, 0, 0))
onewire.show()


def onewire_off():
    onewire.fill((0, 0, 0))
    onewire.show()


def onewire_seq_test(color=(0, 255, 0), step_s=0.15):
    """Init test: postupne rozsvit + postupne zhasinat pixel po pixelu."""
    for i in range(N_ONEWIRE_PIXELS):
        onewire[i] = color
        onewire.show()
        time.sleep(step_s)
        onewire[i] = (0, 0, 0)
        onewire.show()


def onewire_smoke_test():
    """R/G/B na celem retezu - rychla diagnostika HW."""
    print("[1WIRE] smoke RED..."); onewire.fill((255, 0, 0)); onewire.show(); time.sleep(0.6)
    print("[1WIRE] smoke GREEN..."); onewire.fill((0, 255, 0)); onewire.show(); time.sleep(0.6)
    print("[1WIRE] smoke BLUE..."); onewire.fill((0, 0, 255)); onewire.show(); time.sleep(0.6)
    onewire_off()


# ====================================================================
# Buzzer (GP28) - jen digital output 1/0, neblokujici prehravac rytmu
# Aktivni buzzer ma pevnou frekvenci - melodie jsou rytmicke (delky pipu).
# Nezabira PWM slice, takze neni v konfliktu s GP12 (STAVBA).
# ====================================================================
print("[INIT] buzzer (digital) na GPIO {}".format(BUZZER_PIN))
buzzer_pin = digitalio.DigitalInOut(gp(BUZZER_PIN))
buzzer_pin.direction = digitalio.Direction.OUTPUT
buzzer_pin.value = False

# Rytmus = posloupnost (level: bool, doba_ms: int).
# True = buzzer zni, False = ticho.
PIP_SHORT = (True, 80)
PIP_LONG = (True, 200)
REST_SHORT = (False, 60)
REST_MED = (False, 120)

# Po stisku SW4 / startu PustAuto - jedno sustained "PIIIIP"
RHYTHM_SW4 = (
    (True, 280),
)

buzzer_seq = None
buzzer_idx = 0
buzzer_next_t = 0.0


def _buzzer_apply_step(t):
    """Aplikuje aktualni krok na hardware a nastavi cas dalsiho prepnuti."""
    global buzzer_next_t
    level, dur_ms = buzzer_seq[buzzer_idx]
    buzzer_pin.value = level
    buzzer_next_t = t + dur_ms / 1000.0


def buzzer_play_rhythm(seq):
    """Spusti neblokujici prehravani rytmu."""
    global buzzer_seq, buzzer_idx
    if len(seq) == 0:
        return
    buzzer_seq = seq
    buzzer_idx = 0
    _buzzer_apply_step(time.monotonic())
    print("[BUZZER] rytmus ({} kroku)".format(len(seq)))


def buzzer_pip():
    """Zkratka pro jeden kratky pip."""
    buzzer_play_rhythm((PIP_SHORT,))


def buzzer_silence():
    global buzzer_seq
    buzzer_pin.value = False
    buzzer_seq = None


def buzzer_tick(t):
    global buzzer_idx, buzzer_seq
    if buzzer_seq is None:
        return
    if t < buzzer_next_t:
        return
    buzzer_idx += 1
    if buzzer_idx >= len(buzzer_seq):
        buzzer_pin.value = False
        buzzer_seq = None
        return
    _buzzer_apply_step(t)


# ====================================================================
# Exkluzivni dvojice GPIO 0/1 - alternovani (prikaz 'A', SW5)
# ====================================================================
alt_mode = False
alt_start = 0.0


def alt_start_now():
    global alt_mode, alt_start
    alt_mode = True
    alt_start = time.monotonic()
    set_led(EXCLUSIVE_PAIR[0], True)
    set_led(EXCLUSIVE_PAIR[1], False)


def alt_stop():
    global alt_mode
    alt_mode = False


def alt_tick(t):
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


# ====================================================================
# HRA funkce - kazda ma start/stop/tick
# ====================================================================

# ---- PozorStavba (auto on boot, blika POZOR LED 5/6) ----
pozor_active = False
pozor_paused = False  # po manualnim toggle LED 5/6 v REPL
pozor_last_t = 0.0
pozor_state = 0       # 0: LED5 ON / LED6 OFF, 1: LED5 OFF / LED6 ON


def pozor_start():
    global pozor_active, pozor_last_t, pozor_state, pozor_paused
    pozor_active = True
    pozor_paused = False
    pozor_last_t = time.monotonic()
    pozor_state = 0
    set_led(POZOR_PINS[0], True)
    set_led(POZOR_PINS[1], False)
    print("[POZOR] PozorStavba START")


def pozor_stop():
    global pozor_active
    pozor_active = False
    set_led(POZOR_PINS[0], False)
    set_led(POZOR_PINS[1], False)
    print("[POZOR] PozorStavba STOP")


def pozor_pause():
    global pozor_paused
    pozor_paused = True


def pozor_resume():
    global pozor_paused, pozor_last_t, pozor_state
    pozor_paused = False
    pozor_last_t = time.monotonic()
    pozor_state = 0
    set_led(POZOR_PINS[0], True)
    set_led(POZOR_PINS[1], False)
    print("[POZOR] obnoveno")


def pozor_tick(t):
    global pozor_last_t, pozor_state
    if not pozor_active or pozor_paused:
        return
    if (t - pozor_last_t) >= POZOR_BLINK_S:
        pozor_state ^= 1
        set_led(POZOR_PINS[0], pozor_state == 0)
        set_led(POZOR_PINS[1], pozor_state == 1)
        pozor_last_t = t


# ---- vabeniKoristi (LED 11, breathing 50% PWM_MAX) ----
vabeni_active = False
vabeni_start_t = 0.0
vabeni_scheduled_at = None  # plan pro start (po bootu nebo po END SEMAFORu)


def vabeni_schedule(delay_s):
    global vabeni_scheduled_at
    vabeni_scheduled_at = time.monotonic() + delay_s
    print("[VABENI] planovano za {:.1f} s".format(delay_s))


def vabeni_start():
    global vabeni_active, vabeni_start_t, vabeni_scheduled_at
    vabeni_active = True
    vabeni_start_t = time.monotonic()
    vabeni_scheduled_at = None
    print("[VABENI] START (LED {}, breathing)".format(TLACITKO_PIN))


def vabeni_stop():
    global vabeni_active, vabeni_scheduled_at
    vabeni_active = False
    vabeni_scheduled_at = None
    set_led(TLACITKO_PIN, False)


def vabeni_tick(t):
    global vabeni_active
    if vabeni_scheduled_at is not None and t >= vabeni_scheduled_at:
        vabeni_start()
    if not vabeni_active:
        return
    # Jeden tep = plynuly nabeh i dobeh jasu (rozsvicena cast), pak kratka tma.
    # Tma je pevne VABENI_DARK_S (max 300 ms), zbytek periody je rozsvicena cast.
    cyc = (t - vabeni_start_t) % VABENI_PERIOD_S
    lit_dur = VABENI_PERIOD_S - VABENI_DARK_S
    if cyc < lit_dur:
        # sin(0..pi): 0 -> 1 -> 0 (hladky fade-in i fade-out) + gamma korekce
        level = math.sin(cyc / lit_dur * math.pi) ** VABENI_GAMMA
    else:
        level = 0.0
    # max 50 % z PWM_MAX (specifikum vabeniKoristi)
    target = level * 0.5 * PWM_MAX_PCT[TLACITKO_PIN]
    apply_led_with_duty(TLACITKO_PIN, int(target))


# ---- MajakBuldozer (LED 7, sawtooth: 0..MAX se kratkym holdem na MAX) ----
majak_active = False
majak_start_t = 0.0


def majak_start():
    global majak_active, majak_start_t
    majak_active = True
    majak_start_t = time.monotonic()
    print("[MAJAK] MajakBuldozer START")


def majak_stop():
    global majak_active
    majak_active = False
    set_led(BULDOZER_PIN, False)
    print("[MAJAK] MajakBuldozer STOP")


def majak_toggle():
    if majak_active:
        majak_stop()
    else:
        majak_start()


def majak_tick(t):
    if not majak_active:
        return
    # majak: hladky sinusoidalni prulet 0 -> MAX -> 0 v ramci jedne periody.
    # sin^N drzi LED vetsinu casu pri nule a kratce vyletne na MAX (efekt majaku).
    phase = ((t - majak_start_t) % MAJAK_PERIOD_S) / MAJAK_PERIOD_S
    s = math.sin(phase * math.pi)        # 0 -> 1 -> 0 (jedna pulvlna)
    amp = s ** MAJAK_SHAPE_POW            # zostri vrchol, prodlouzi tichou cast
    target = amp * PWM_MAX_PCT[BULDOZER_PIN]
    apply_led_with_duty(BULDOZER_PIN, int(target))


# ---- RozsvitJerab (sekvence + zluta po 4s problikava) ----
jerab_active = False
jerab_step = 0
jerab_last_t = 0.0
jerab_yellow_started = False
jerab_yellow_t = 0.0
jerab_yellow_state = False  # False=RED ON (zluta OFF), True=YELLOW ON (cervena OFF)
jerab_yellow_phase_t = 0.0
JERAB_INIT_DELAY_S = JERAB_INIT_DELAY_MS / 1000.0


def jerab_start():
    global jerab_active, jerab_step, jerab_last_t, jerab_yellow_started, jerab_yellow_state
    jerab_active = True
    jerab_step = 0
    jerab_last_t = time.monotonic()
    jerab_yellow_started = False
    jerab_yellow_state = False
    print("[JERAB] RozsvitJerab START")


def jerab_stop():
    global jerab_active, jerab_yellow_started
    jerab_active = False
    jerab_yellow_started = False
    for n in JERAB_PINS:
        set_led(n, False)
    print("[JERAB] RozsvitJerab STOP")


def jerab_tick(t):
    global jerab_step, jerab_last_t, jerab_yellow_started
    global jerab_yellow_t, jerab_yellow_state, jerab_yellow_phase_t
    if not jerab_active:
        return
    # 1. faze: postupne zapinani LED z JERAB_PINS_NO_YELLOW
    if jerab_step < len(JERAB_PINS_NO_YELLOW):
        if (t - jerab_last_t) >= JERAB_INIT_DELAY_S:
            n = JERAB_PINS_NO_YELLOW[jerab_step]
            set_led(n, True)
            jerab_step += 1
            jerab_last_t = t
        return
    # 2. faze: cekani 4 s po posledni LED, pak start problikavani GPIO 0 vs GPIO 1
    if not jerab_yellow_started:
        if (t - jerab_last_t) >= JERAB_YELLOW_START_DELAY_S:
            jerab_yellow_started = True
            jerab_yellow_state = True  # zacni zlutou
            set_led(0, False)
            set_led(JERAB_YELLOW, True)
            jerab_yellow_phase_t = t
            print("[JERAB] zluta zacina problikavat")
        return
    # 3. faze: stridani RED (3 s) / YELLOW (300 ms)
    if jerab_yellow_state:
        # zluta sviti
        if (t - jerab_yellow_phase_t) >= JERAB_YELLOW_ON_S:
            set_led(JERAB_YELLOW, False)
            set_led(0, True)
            jerab_yellow_state = False
            jerab_yellow_phase_t = t
    else:
        # cervena sviti
        if (t - jerab_yellow_phase_t) >= JERAB_RED_ON_S:
            set_led(0, False)
            set_led(JERAB_YELLOW, True)
            jerab_yellow_state = True
            jerab_yellow_phase_t = t


# ---- RozsvitStavbu (STAVBA fade-in jako sodikova vybojka + zrcadlovy fade-out) ----
# Stavovy automat sledujici prubeh jasu:
#   "idle"      - LED zhasnuta
#   "fade_in"   - rozsviceni (kvadraticka krivka, pomale na zacatku)
#   "on"        - sviti na PWM_MAX
#   "fade_out"  - zhasinani (zrcadlova krivka, plynule z aktualniho jasu)
# Pri opakovanem stisku/uvolneni SW3 behem prechodu se faze prelozi a pokracuje
# plynule z aktualni urovne jasu (zadny skok dolu/nahoru).
stavba_phase = "idle"
stavba_current_pct = 0.0    # aktualni jas v % (float pro plynulost)
stavba_last_tick_t = 0.0


def stavba_start():
    """SW3 STISK - rozsviceni. Pokud bezi fade-out, plynule prejde do fade-in."""
    global stavba_phase, stavba_last_tick_t
    if stavba_phase == "on":
        return
    stavba_phase = "fade_in"
    stavba_last_tick_t = time.monotonic()
    set_led(MICHACKA_PIN, True)
    led_on[STAVBA_PIN] = True
    print("[STAVBA] RozsvitStavbu START (fade-in z {:.0f}%)".format(stavba_current_pct))


def stavba_stop():
    """SW3 UVOLNENI - spusti zrcadlovy fade-out z aktualniho jasu."""
    global stavba_phase, stavba_last_tick_t
    if stavba_phase == "idle":
        return
    stavba_phase = "fade_out"
    stavba_last_tick_t = time.monotonic()
    set_led(MICHACKA_PIN, False)
    print("[STAVBA] RozsvitStavbu STOP (fade-out z {:.0f}%)".format(stavba_current_pct))


def stavba_force_off():
    """Okamzite vypnuti bez fade-out (pouziva sleepBox / stop_all_hra)."""
    global stavba_phase, stavba_current_pct
    stavba_phase = "idle"
    stavba_current_pct = 0.0
    set_led(MICHACKA_PIN, False)
    set_led(STAVBA_PIN, False)


def stavba_tick(t):
    """Krok nelinearniho prechodu mezi 0 a PWM_MAX. Krivka pct = frac^2 * MAX
    (sodikova vybojka - pomale na zacatku, rychle na konci)."""
    global stavba_current_pct, stavba_phase, stavba_last_tick_t
    if stavba_phase == "idle":
        return
    dt = t - stavba_last_tick_t
    stavba_last_tick_t = t
    MAX = PWM_MAX_PCT[STAVBA_PIN]
    if MAX <= 0:
        return
    # vypocti aktualni "frac" z aktualniho pct (kvuli plynulemu prechodu fazi)
    frac = math.sqrt(stavba_current_pct / MAX) if stavba_current_pct > 0 else 0.0

    if stavba_phase == "fade_in":
        frac += dt / STAVBA_FADE_IN_S
        if frac >= 1.0:
            stavba_current_pct = MAX
            stavba_phase = "on"
        else:
            stavba_current_pct = frac * frac * MAX
    elif stavba_phase == "fade_out":
        frac -= dt / STAVBA_FADE_OUT_S
        if frac <= 0.0:
            stavba_current_pct = 0.0
            stavba_phase = "idle"
            led_on[STAVBA_PIN] = False
        else:
            stavba_current_pct = frac * frac * MAX
    # "on" - drz MAX, nic nepocitej
    apply_led_with_duty(STAVBA_PIN, int(stavba_current_pct))


# ---- PustAuto (SEMAFOR) - state machine ----
SEM_IDLE, SEM_INIT, SEM_RUN, SEM_GO, SEM_ODJETO, SEM_END = 0, 1, 2, 3, 4, 5
sem_state = SEM_IDLE
sem_t = 0.0      # cas vstupu do aktualni faze
sem_sub_t = 0.0  # casovac uvnitr faze
sem_sub = 0
sem_was_vabeni = False  # mela vabeni bezet pred SEMAFOR?


def sem_start():
    """SW4 - tlacitko, dobehne dokonce. Pri zapnuti deaktivuje vabeniKoristi.
    Pokud uz sekvence bezi, ignoruje opakovany stisk (zadny zvuk, zadne restartovani)."""
    global sem_state, sem_t, sem_sub, sem_sub_t, sem_was_vabeni
    if sem_state != SEM_IDLE:
        print("[SEMAFOR] uz bezi, ignoruji nove spusteni")
        return
    # zvuk zaroven se spustenim sekvence - jen pri uspesnem startu
    buzzer_play_rhythm(RHYTHM_SW4)
    sem_was_vabeni = vabeni_active or (vabeni_scheduled_at is not None)
    if vabeni_active or vabeni_scheduled_at is not None:
        vabeni_stop()
    sem_state = SEM_INIT
    sem_t = time.monotonic()
    sem_sub = 0
    sem_sub_t = sem_t
    # INIT: sviti cervena na semaforu + 1. OneWire bila
    set_led(SEMAFOR_RED, True)
    set_led(SEMAFOR_YELLOW, False)
    set_led(SEMAFOR_GREEN, False)
    onewire.fill((0, 0, 0))
    onewire[0] = (255, 255, 255)
    onewire.show()
    print("[SEMAFOR] PustAuto START (INIT)")


def sem_abort():
    """Force-stop (napr. v sleepBoxu)."""
    global sem_state
    sem_state = SEM_IDLE
    set_led(SEMAFOR_RED, False)
    set_led(SEMAFOR_YELLOW, False)
    set_led(SEMAFOR_GREEN, False)
    onewire_off()


def sem_tick(t):
    global sem_state, sem_t, sem_sub, sem_sub_t
    if sem_state == SEM_IDLE:
        return
    dt = t - sem_t

    if sem_state == SEM_INIT:
        # cekame SEM_INIT_HOLD_S, pak RUN_SEMAFOR
        if dt >= SEM_INIT_HOLD_S:
            sem_state = SEM_RUN
            sem_t = t
            sem_sub = 0
            sem_sub_t = t
            print("[SEMAFOR] -> RUN_SEMAFOR")
        return

    if sem_state == SEM_RUN:
        # RED -> RED+YELLOW (kratce) -> GREEN, klasicky semafor
        if sem_sub == 0:
            # RED hori - po SEM_RUN_RED_TO_YELLOW_S pridej YELLOW
            if (t - sem_sub_t) >= SEM_RUN_RED_TO_YELLOW_S:
                set_led(SEMAFOR_YELLOW, True)
                sem_sub = 1
                sem_sub_t = t
        elif sem_sub == 1:
            # RED + YELLOW po SEM_RUN_YELLOW_S -> jen GREEN
            if (t - sem_sub_t) >= SEM_RUN_YELLOW_S:
                set_led(SEMAFOR_RED, False)
                set_led(SEMAFOR_YELLOW, False)
                set_led(SEMAFOR_GREEN, True)
                sem_sub = 2
                sem_sub_t = t
        elif sem_sub == 2:
            # GREEN drz pak prejdi do GO
            if (t - sem_sub_t) >= SEM_RUN_GREEN_HOLD_S:
                sem_state = SEM_GO
                sem_t = t
                sem_sub = 0
                sem_sub_t = t
                onewire.fill((0, 0, 0))
                onewire.show()
                print("[SEMAFOR] -> GO (zelena + ridici cara)")
        return

    if sem_state == SEM_GO:
        # rozjizdejici se cara - prvni pixel sviti dlouho, posledni kratce
        elapsed = t - sem_t
        if elapsed >= SEM_GO_TO_ODJETO_S:
            onewire.fill((0, 0, 0))
            onewire.show()
            sem_state = SEM_ODJETO
            sem_t = t
            sem_sub = 0
            sem_sub_t = t
            print("[SEMAFOR] -> ODJETO")
            return
        # vypocet ktery pixel aktualne sviti a jeho jas
        # casovani zrychluje: pixel i sviti dt_i = base * (N-i)/N
        # zjednodusene rozpocitej okno SEM_GO_TO_ODJETO_S na N pixelu nelinearne
        # frac = elapsed / SEM_GO_TO_ODJETO_S, lehce zrychlujici -> sqrt
        frac = elapsed / SEM_GO_TO_ODJETO_S
        idx = int(frac * N_ONEWIRE_PIXELS)
        if idx >= N_ONEWIRE_PIXELS:
            idx = N_ONEWIRE_PIXELS - 1
        onewire.fill((0, 0, 0))
        # rozsvit aktualni s plnym jasem a predchozi se zhasinanim (efekt jedouci cary)
        bright = 255
        onewire[idx] = (bright, bright, bright)
        if idx >= 1:
            onewire[idx - 1] = (bright // 4, bright // 4, bright // 4)
        onewire.show()
        return

    if sem_state == SEM_ODJETO:
        # zelena -> zluta -> cervena, pak konec
        if sem_sub == 0:
            # zelena dosviti
            if (t - sem_sub_t) >= SEM_ODJETO_GREEN_HOLD_S:
                set_led(SEMAFOR_GREEN, False)
                set_led(SEMAFOR_YELLOW, True)
                sem_sub = 1
                sem_sub_t = t
        elif sem_sub == 1:
            # zluta
            if (t - sem_sub_t) >= SEM_ODJETO_YELLOW_S:
                set_led(SEMAFOR_YELLOW, False)
                set_led(SEMAFOR_RED, True)
                sem_sub = 2
                sem_sub_t = t
        elif sem_sub == 2:
            # cervena drz SEM_ODJETO_TO_END_S -> END
            if (t - sem_sub_t) >= SEM_ODJETO_TO_END_S:
                set_led(SEMAFOR_RED, False)
                sem_state = SEM_END
                sem_t = t
                print("[SEMAFOR] -> END")
        return

    if sem_state == SEM_END:
        # vse zhasnuto. naplanuj vabeniKoristi (zadani: prodleni asi 4 s)
        onewire_off()
        sem_state = SEM_IDLE
        vabeni_schedule(4.0)
        print("[SEMAFOR] DONE")
        return


# ---- Vsechny LED ON (SW5, prikaz A v REPL) ----
def all_leds_on():
    for n in LED_PINS:
        if n in EXCLUSIVE_PAIR:
            continue
        set_led(n, True)
    alt_start_now()
    print("[LED] vsechny ON (GPIO 0/1 alternuji {} s)".format(ALT_PERIOD_S))


def all_leds_off():
    alt_stop()
    for n in LED_PINS:
        set_led(n, False)
    print("[LED] vsechny OFF")


# ====================================================================
# SleepBox + ShutDown
# ====================================================================
last_input_change_t = time.monotonic()
sleepbox_active = False
sleepbox_entered_t = 0.0


def stop_all_hra():
    """Zastavi vsechny HRA funkce (krome systemoveho keep-alive)."""
    if majak_active:
        majak_stop()
    if jerab_active:
        jerab_stop()
    if stavba_phase != "idle":
        stavba_force_off()   # sleepBox = okamzite, ne fade-out
    if sem_state != SEM_IDLE:
        sem_abort()
    if vabeni_active or vabeni_scheduled_at is not None:
        vabeni_stop()
    if pozor_active:
        pozor_stop()
    if alt_mode:
        alt_stop()
    buzzer_silence()
    # vypni vsechny LED (PWM 0..15 + OneWire)
    for n in LED_PINS:
        set_led(n, False)
    onewire_off()


def sleepbox_enter():
    global sleepbox_active, sleepbox_entered_t
    if sleepbox_active:
        return
    sleepbox_active = True
    sleepbox_entered_t = time.monotonic()
    stop_all_hra()
    print("[SLEEPBOX] aktivovano (vstupy {:.0f}s neaktivni). ShutDown za {:.0f}s.".format(
        SLEEP_BOX_TIMEOUT_S, SHUTDOWN_TIMEOUT_S))


def sleepbox_exit():
    global sleepbox_active, last_input_change_t
    if not sleepbox_active:
        return
    sleepbox_active = False
    last_input_change_t = time.monotonic()
    # HRA do defaultniho stavu: PozorStavba znovu + vabeniKoristi naplanovat
    pozor_start()
    vabeni_schedule(VABENI_BOOT_DELAY_S)
    print("[SLEEPBOX] deaktivovano. HRA reset na defaulty.")


def shutdown_now():
    print("[SHUTDOWN] casovac vyprsel, vypinam keep-alive. System se vypne.")
    keep_alive_off()
    # po vypnuti keep-alive zustaneme v idle smycce - ext. HW odrizne napajeni
    while True:
        time.sleep(1.0)


# ====================================================================
# Init test LED po skupinach (vc. OneWire)
# ====================================================================
print("[INIT] Test LED po skupinach (LED po LED)...")
time.sleep(0.3)
for name, pins in LED_GROUPS_INIT:
    print("[INIT]   skupina {:8s} -> GPIO {}".format(name, list(pins)))
    for n in pins:
        set_led(n, True)
        time.sleep(LED_TEST_ON_S)
        set_led(n, False)
print("[INIT] Test PWM LED hotov.")

print("[INIT] Test 1-wire LED - sekvence (zelena, pixel po pixelu, rozsvit+zhasnout)...")
onewire_seq_test(color=(0, 255, 0), step_s=0.15)
print("[INIT] Test 1-wire LED hotov.")


# ====================================================================
# Inputs (debounced)
# ====================================================================
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
print("[INIT]   vstupy pripraveny: {}".format(
    {n: ("HIGH" if confirmed[n] else "LOW") for n in INPUT_PINS}))


# ====================================================================
# REPL parser (Enter-confirmed, echo, backspace)
# ====================================================================
input_buffer = ""


def echo(s):
    # print s end="" je v CP spolehlivejsi flush nez sys.stdout.write
    print(s, end="")


def echo_backspace():
    print("\b \b", end="")


def print_help():
    print("-" * 60)
    print("HYBRIDNI REPL:")
    print("  INSTANT (bez Enteru, vyhodnoceni hned po stisknuti):")
    print("    0..9 a..f -> toggle LED GPIO 0..15 (hex)")
    print("    A         -> vsechny LED ON (GPIO 0/1 alternuji {} s)".format(ALT_PERIOD_S))
    print("    Z         -> vsechny LED OFF")
    print("    S         -> vypis svitici LED")
    print("    N         -> opakovat 1-wire LED test")
    print("    B         -> toggle MajakBuldozer")
    print("    X         -> obnovit PozorStavba (po manualnim toggle 5/6)")
    print("    + / -     -> +-5 % na posledni LED z 'P<hex>=<n>'")
    print("    ?         -> tato napoveda")
    print("  BUFFER + ENTER (mezera/tab/Enter potvrdi):")
    print("    W            -> zapnout keep-alive")
    print("    Woff         -> vypnout keep-alive")
    print("    D            -> vypis duty vsech LED")
    print("    D<n>         -> duty 0..100 % pro VSECHNY LED (clamp na MAX)")
    print("    F            -> vypis aktualni PWM freq")
    print("    F<n>         -> nastav PWM freq v Hz")
    print("    P            -> vypis duty + PWM_MAX per LED")
    print("    P<hex>=<n>   -> duty pro jednu LED a zapnout (napr. Pa=30)")
    print("    FactoryRESET -> default hodnoty (z LED-Table) + NVM")
    print("Aktualne: freq={} Hz, ka_enabled={}".format(pwm_freq, ka_enabled))
    print("-" * 60)


last_p_target = None  # posledni LED nastavena prikazem P<hex>=<n>


def handle_command(cmd):
    """Vyhodnoti jeden cely radek - po Enteru."""
    global last_p_target
    cmd = cmd.strip()
    if not cmd:
        return

    # FactoryRESET (case-sensitive)
    if cmd == "FactoryRESET":
        factory_reset()
        return

    # Vse ostatni - cmd je krátky token. Pokud jeden znak:
    if len(cmd) == 1:
        ch = cmd
        if ch in HEX_DIGITS:
            n = int(ch, 16)
            if n in EXCLUSIVE_PAIR and alt_mode:
                alt_stop()
                print("[LED] alternovani GPIO {}/{} ukonceno (manualni toggle)".format(*EXCLUSIVE_PAIR))
            set_led(n, not led_on[n])
            print("[LED] GPIO {:2d} = {}".format(n, "ON " if led_on[n] else "OFF"))
            # manualni toggle LED 5/6 pauzuje PozorStavba
            if n in POZOR_PINS:
                pozor_pause()
                print("[POZOR] pauzovano kvuli manualnimu toggle (obnov: X)")
            return
        if ch == "A":
            all_leds_on(); return
        if ch == "Z":
            all_leds_off(); return
        if ch == "S":
            svici = [n for n in LED_PINS if led_on[n]]
            print("[LED] svici GPIO: {}".format(svici)); return
        if ch == "?":
            print_help(); return
        if ch == "W":
            keep_alive_on(); return
        if ch == "N":
            onewire_smoke_test()
            onewire_seq_test(color=(0, 255, 0), step_s=0.15)
            return
        if ch == "B":
            majak_toggle(); return
        if ch == "X":
            pozor_resume(); return
        if ch == "D":
            print("[PWM] duty per LED: {}".format(led_duty_pct)); return
        if ch == "P":
            print("[PWM] per LED (duty / MAX):")
            for n in LED_PINS:
                print("  GPIO {:2d}: {:3d} % / MAX {:3d} %".format(n, led_duty_pct[n], PWM_MAX_PCT[n]))
            return
        if ch == "F":
            print("[PWM] frequency = {} Hz".format(pwm_freq)); return
        if ch == "+":
            if last_p_target is None:
                print("[PWM] + krok: nejdriv pouzij P<hex>=<n>")
                return
            set_led_duty(last_p_target, led_duty_pct[last_p_target] + 5)
            return
        if ch == "-":
            if last_p_target is None:
                print("[PWM] - krok: nejdriv pouzij P<hex>=<n>")
                return
            set_led_duty(last_p_target, led_duty_pct[last_p_target] - 5)
            return
        print("[!] neznamy znak: {!r}".format(ch))
        return

    # Viceznakove prikazy
    if cmd == "Woff":
        keep_alive_off(); return

    # D<n> - duty pro vsechny
    if cmd[0] == "D" and cmd[1:].isdigit():
        set_all_duty(int(cmd[1:])); return

    # F<n> - frekvence
    if cmd[0] == "F" and cmd[1:].isdigit():
        set_pwm_freq(int(cmd[1:])); return

    # P<hex>=<n> - duty pro jednu LED
    if cmd[0] == "P" and "=" in cmd:
        left, right = cmd[1:].split("=", 1)
        if len(left) == 1 and left in HEX_DIGITS and right.isdigit():
            n = int(left, 16)
            last_p_target = n
            set_led_duty(n, int(right))
            return

    print("[!] neznamy prikaz: {!r}".format(cmd))


REPL_DEBUG = False  # True = vypis ord() prichozich znaku (jen pro debug)

# Hybridni REPL: tyto znaky se vyhodnoti hned bez Enteru
INSTANT_CHARS = set("0123456789abcdefAZSNBX+-?")
# Tyto znaky startuji multi-char prikaz - vstup do bufferu, ceka se na Enter
BUFFER_START_CHARS = set("WDFP")


def repl_feed_char(ch):
    """Hybridni parser:
      - prazdny buffer + INSTANT_CHARS  -> okamzite vrati ch jako 'line'
      - prazdny buffer + BUFFER_START_CHARS -> vstup do bufferu, echo
      - neprazdny buffer -> akumuluje az do terminatoru (Enter/space/tab)
    """
    global input_buffer
    if REPL_DEBUG:
        print("[REPL-DBG] rx ord={}".format(ord(ch)))

    # Terminator (Enter / space / tab) - flushne buffer (pokud neco je)
    if ch in ("\r", "\n", " ", "\t"):
        if input_buffer:
            print("")  # newline po echo
            line = input_buffer
            input_buffer = ""
            return line
        return None

    # Backspace / DEL - maze posledni znak v bufferu
    if ch in ("\x7f", "\b"):
        if input_buffer:
            input_buffer = input_buffer[:-1]
            echo_backspace()
        return None

    # Filtrace netisknutelnych znaku
    if not (0x21 <= ord(ch) <= 0x7E):
        return None

    # Buffer mod - pokracuj v akumulaci
    if input_buffer:
        input_buffer += ch
        echo(ch)
        return None

    # Prazdny buffer - rozhodni mezi instant a buffer-start
    if ch in INSTANT_CHARS:
        # echo s newline, hned vyhodnotit
        print(ch)
        return ch
    if ch in BUFFER_START_CHARS:
        input_buffer = ch
        echo(ch)
        return None

    # Neznamy single-char znak
    print("[!] neznamy znak: {!r}".format(ch))
    return None


# ====================================================================
# HRA - bootovaci stav: PozorStavba + naplanovani vabeniKoristi
# ====================================================================
print("=" * 60)
print("EdyKostka - HRA")
print("=" * 60)
print_help()

pozor_start()
vabeni_schedule(VABENI_BOOT_DELAY_S)

print(">>> REPL ready (hybrid: 0..9 a..f A Z S N B X +/- ? fire hned; W D F P + Enter) <<<")


# ====================================================================
# Switch dispatch
# ====================================================================
def on_switch_change(pin, pressed):
    """pressed=True znamena hrana stisku (HIGH -> LOW)."""
    event = "STISK" if pressed else "uvolneno"
    print("[VSTUP] GPIO {} -> {}".format(pin, event))

    if pin == SW1_PIN:
        if pressed:
            majak_start()
        else:
            majak_stop()
    elif pin == SW2_PIN:
        if pressed:
            jerab_start()
        else:
            jerab_stop()
    elif pin == SW3_PIN:
        if pressed:
            stavba_start()
        else:
            stavba_stop()
    elif pin == SW4_PIN:
        # tlacitko - jen na nabeznou hranu, dobehne dokonce.
        # sem_start si sam zvolil jestli prehrat zvuk (jen pri uspesnem startu).
        if pressed:
            sem_start()
    elif pin == SW5_PIN:
        if pressed:
            all_leds_on()
        else:
            all_leds_off()


# ====================================================================
# Main loop
# ====================================================================
while True:
    t = time.monotonic()

    # --- serial input ---
    if supervisor.runtime.serial_bytes_available:
        ch = sys.stdin.read(1)
        line = repl_feed_char(ch)
        if line is not None:
            handle_command(line)

    # --- inputs s debouncingem ---
    any_input_change = False
    for n in INPUT_PINS:
        v = inputs[n].value
        if v != raw_state[n]:
            raw_state[n] = v
            raw_changed_at[n] = t
        elif v != confirmed[n] and (t - raw_changed_at[n]) > DEBOUNCE_S:
            confirmed[n] = v
            any_input_change = True
            pressed = (v is False)  # aktivni LOW
            if sleepbox_active:
                sleepbox_exit()
            on_switch_change(n, pressed)
    if any_input_change:
        last_input_change_t = t

    # --- sleepBox / ShutDown ---
    if not sleepbox_active:
        if (t - last_input_change_t) > SLEEP_BOX_TIMEOUT_S:
            sleepbox_enter()
    else:
        if (t - sleepbox_entered_t) > SHUTDOWN_TIMEOUT_S:
            shutdown_now()

    # --- ticky ---
    keep_alive_tick(t)
    if not sleepbox_active:
        alt_tick(t)
        pozor_tick(t)
        vabeni_tick(t)
        majak_tick(t)
        jerab_tick(t)
        stavba_tick(t)
        sem_tick(t)
        buzzer_tick(t)

    time.sleep(0.005)
