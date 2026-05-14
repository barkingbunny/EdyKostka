"""
EdyKostka - HRA + bring-up nastroj.

HRA (po bootu bezi automaticky):
  - keep-alive: perioda 10 s, pulz HIGH 400 ms (bezi na pozadi)
  - PozorStavba: alternujici blikani GPIO 5 / 6 (varovny semafor)
SWITCHE (aktivni LOW, reaguji na hrany):
  SW1 (GPIO 18) -> MajakBuldozer    (start/stop)
  SW2 (GPIO 19) -> RozsvitJerab     (start/stop)
  SW3 (GPIO 22) -> RozsvitStavbu    (start/stop)
  SW4 (GPIO 20) -> PustAuto         (momentova OFF-(ON); funkce dobehne dokonce)
  SW5 (GPIO 21) -> vsechny LED ON   (OFF-ON)

AUTO funkce na pozadi:
  - vabeniKoristi: pulzuje GPIO 11 na 50 %, start ~5 s po nabehnuti HRA.
    Pri startu PustAuto se vypne, po END PustAuto se znovu zapne.

REPL (serial, bez Enteru):
  0..9 a..f  - toggle LED GPIO 0..15 (hex; 5/6 pauzuje PozorStavba)
  A / Z      - vsechny ON / vsechny OFF
  S          - stav LED
  X          - obnovit PozorStavba po manualnim toggle 5/6
  W / Woff   - keep-alive ON / OFF
  N          - opakovat 1-wire LED test
  B          - toggle MajakBuldozer
  D<n>       - duty pro vsechny LED (clamped na PWM_MAX z tabulky)
  P<hex>=<n> - duty pro jednu LED + zapnout
  + / -      - 5% krok na posledni 'P' LED
  P          - vypis duty + PWM_MAX vsech LED
  F<n>       - PWM frekvence
  ?          - help

PWM MAX (tabulka v zadani): kazda LED ma per-pin limit, hardware nikdy
nedostane vyssi duty (clamping v _clamp_pct + _duty_value).
"""

import board
import digitalio
import math
import pwmio
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

# HRA - mapovani switchu (zadani sekce HRA):
SW1_BULDOZER_PIN = 18       # SWITCH 1 - MajakBuldozer
SW2_JERAB_PIN = 19          # SWITCH 2 - RozsvitJerab
SW3_STAVBA_PIN = 22         # SWITCH 3 - RozsvitStavbu (STAVBA + MICHACKA)
SW4_AUTO_PIN = 20           # SWITCH 4 - PustAuto (momentova, OFF-(ON), funkce dobehne dokonce)
SW5_ALL_PIN = 21            # SWITCH 5 - vsechny LED (OFF-ON, dosavadni 'A' chovani)

# GPIO LED pro skupiny pouzite ve spinacove logice
JERAB_PINS = (14, 15, 10, 0, 9, 13, 1)
JERAB_NONEXCLUSIVE = tuple(n for n in JERAB_PINS if n not in (0, 1))
JERAB_STEP_S = 0.1                       # 100 ms krok mezi rozsvecenim JERAB LED
JERAB_TOP_BLINK_DELAY_S = 4.0            # po 4 s zacne TOP blikat
JERAB_TOP_RED_S = 3.0                    # 3 s sviti RED (GPIO 0)
JERAB_TOP_YELLOW_S = 0.3                 # 300 ms sviti YELLOW (GPIO 1)
SEMAFOR_SEQUENCE = (3, 2, 4)             # RED -> YELLOW -> GREEN (drzeno pro init test)
SEMAFOR_STEP_S = 0.4
POZOR_PINS = (5, 6)                      # POZOR LEFT/RIGHT
POZOR_HALF_PERIOD_S = 0.5                # 500 ms stridani 5 <-> 6
STAVBA_LED_PIN = 12                      # STAVBA TOP (WHITE)
MICHACKA_LED_PIN = 8                     # MICHACKA FRONT (YELLOW)
# vabeniKoristi - svetlo TLACITKO (GPIO 11), pulzuje aby privabilo pozornost
VABENI_LED_PIN = 11
VABENI_MAX_PCT = 50                      # 50 % maxima (dle zadani)
VABENI_PERIOD_S = 2.5                    # pomalejsi pulzovani nez buldozer
VABENI_BOOT_DELAY_S = 5.0                # auto-start ~5 s po nabehnuti HRA
VABENI_POST_AUTO_DELAY_S = 4.0           # prodleva ~4 s po PustAuto END (dle zadani)

DEBOUNCE_S = 0.03
KA_PERIOD_S = 10.0

# sleepBox / ShutDown - dle sekce "System" v zadani.
# Default 600 s (10 min). Pro testovani lze ladit na kratsi hodnoty.
SLEEP_BOX_TIMEOUT_S = 600.0   # necinnost vstupu pred prechodem do sleepBox
SHUTDOWN_TIMEOUT_S = 600.0    # doba v sleepBox pred trvalym vypnutim

# --- PWM MAX limity pro jednotlive LED (z tabulky v zadani) ---
# Zaruceno: hardware nikdy nedostane vyssi duty nez tato hodnota.
PWM_MAX_PCT = {
    0: 8,     # JERAB TOP   RED*    (8 %)
    1: 20,    # JERAB TOP   YELLOW* (20 %)
    2: 100,   # SEMAFOR MID YELLOW  (100 %)
    3: 100,   # SEMAFOR TOP RED
    4: 100,   # SEMAFOR BOT GREEN
    5: 100,   # POZOR LEFT  RED
    6: 100,   # POZOR RIGHT RED
    7: 50,    # BULDOZER TOP ORANGE (50 %)
    8: 100,   # MICHACKA FRONT YELLOW
    9: 100,   # JERAB RIGHT RED
    10: 100,  # JERAB CABIN RED
    11: 100,  # SWITCH YELLOW
    12: 40,   # STAVBA TOP WHITE (40 %)
    13: 100,  # JERAB LEFT  RED
    14: 100,  # JERAB BOT   RED
    15: 100,  # JERAB MID   RED
}

# --- PWM nastaveni LED ---
PWM_FREQ_MIN = 8            # Hz - prakticka spodni hranice pwmio na RP2040
PWM_FREQ_MAX = 200000       # Hz - rozumny strop pro LED testovani (nad slyshitelnym pasmem)
PWM_FREQ_DEFAULT = PWM_FREQ_MAX   # bootujeme rovnou na max - vc. init testu
PWM_DUTY_DEFAULT = 100      # % (0..100)

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


# --- LED setup (PWM) ---
print("[INIT] konfigurace 16 PWM LED na GPIO 0..15...")
leds = {}
led_on = {}
led_duty_pct = {}   # per-LED duty 0..100 %; frekvence je spolecna (pwm_freq)
pwm_freq = PWM_FREQ_DEFAULT


def _duty_value(n):
    """Aktualni 'svitici' duty v 0..65535 pro LED n podle led_duty_pct[n]."""
    return int(65535 * led_duty_pct[n] / 100)


def apply_led(n):
    """Zapis duty_cycle na hardware podle led_on[n] a led_duty_pct[n] (s ohledem na invertovane LED)."""
    d = _duty_value(n) if led_on[n] else 0
    if n in INVERTED_LEDS:
        d = 65535 - d
    leds[n].duty_cycle = d


for n in LED_PINS:
    pwm = pwmio.PWMOut(gp(n), frequency=pwm_freq, duty_cycle=0, variable_frequency=False)
    leds[n] = pwm
    led_on[n] = False
    # Default duty per-LED = jeji PWM MAX z tabulky (HW limit). Uzivatel muze
    # snizit pres 'P', ale nezvedne nad PWM_MAX_PCT[n].
    led_duty_pct[n] = PWM_MAX_PCT[n]
    apply_led(n)
print("[INIT]   PWM LED OK. freq={} Hz, per-LED duty=PWM_MAX (viz tabulka), invertovane (HIGH=OFF): {}".format(
    pwm_freq, sorted(INVERTED_LEDS)))


def set_led(n, on):
    led_on[n] = on
    apply_led(n)


def reapply_all_leds():
    for n in LED_PINS:
        apply_led(n)


def _clamp_pct(pct, n=None):
    """Clampuje duty do 0..100 a pokud je `n` zadane, zaroven do 0..PWM_MAX_PCT[n]."""
    if pct < 0:
        return 0
    cap = 100 if n is None else PWM_MAX_PCT.get(n, 100)
    if pct > cap:
        return cap
    return pct


def set_pwm_duty_all(pct):
    """Bulk: nastavi duty vsem 16 LED (kazda se zvlast clampne na sve PWM_MAX_PCT)."""
    pct_in = pct
    capped_any = False
    for n in LED_PINS:
        pct_c = _clamp_pct(pct_in, n)
        if pct_c != pct_in:
            capped_any = True
        led_duty_pct[n] = pct_c
    reapply_all_leds()
    if capped_any:
        print("[PWM] vsechny LED duty = {}% (kde to HW limit dovoli, jinak clamped na PWM_MAX)".format(pct_in))
    else:
        print("[PWM] vsechny LED duty = {}%".format(pct_in))


last_p_led = None         # naposledy editovana LED pres 'P' prikaz (cil pro +/-)
DUTY_STEP_PCT = 5         # krok pro '+' / '-'


def set_led_duty(n, pct):
    """Per-LED: nastavi duty jedne LED. Clampne na PWM_MAX_PCT[n]. Zachova on/off stav.

    Pri zadani pres 'P<hex>=<n>' z REPL LED zaroven zapneme (dle zadani:
    "po nastaveni intenzity automaticky ji zapnout").
    """
    global last_p_led
    requested = pct
    pct = _clamp_pct(pct, n)
    led_duty_pct[n] = pct
    last_p_led = n
    led_on[n] = True       # automaticke zapnuti po nastaveni intenzity
    apply_led(n)
    cap_note = " (clamped z {}% na PWM_MAX={}%)".format(requested, PWM_MAX_PCT[n]) if requested != pct else ""
    print("[PWM] LED GPIO {:2d} duty = {:3d}% ON{}".format(n, pct, cap_note))


def nudge_last_led(delta_pct):
    """+/- krok pro naposledy editovanou LED pres 'P' prikaz."""
    if last_p_led is None:
        print("[PWM] '+/-' funguje az po prvnim 'P<hex>=<n>' prikazu")
        return
    set_led_duty(last_p_led, led_duty_pct[last_p_led] + delta_pct)


def print_all_duties():
    print("[PWM] freq = {} Hz, per-LED duty (max dle tabulky v zadani):".format(pwm_freq))
    for n in LED_PINS:
        mark = "ON " if led_on[n] else "off"
        print("       GPIO {:2d} [{}] = {:3d}%  (max {:3d}%)".format(
            n, mark, led_duty_pct[n], PWM_MAX_PCT[n]))


def set_pwm_freq(hz):
    """Zmena PWM frekvence vsech 16 kanalu - deinit a recreate (kvuli sdileni slice na RP2040).

    Pokud recreate selze, zkusi obnovit puvodni frekvenci, aby pole `leds`
    nezustalo s deinitialized objekty.
    """
    global pwm_freq
    if hz < PWM_FREQ_MIN or hz > PWM_FREQ_MAX:
        print("[PWM] freq mimo rozsah {}..{} Hz".format(PWM_FREQ_MIN, PWM_FREQ_MAX))
        return
    old_freq = pwm_freq
    for n in LED_PINS:
        leds[n].deinit()
    try:
        for n in LED_PINS:
            leds[n] = pwmio.PWMOut(gp(n), frequency=hz, duty_cycle=0, variable_frequency=False)
            apply_led(n)
        pwm_freq = hz
        print("[PWM] frequency = {} Hz".format(pwm_freq))
    except (ValueError, RuntimeError) as e:
        print("[PWM] CHYBA nastaveni freq {} Hz: {} - obnovuji {} Hz".format(hz, e, old_freq))
        for n in LED_PINS:
            # nektere uz mohly byt vytvorene v predchozim pokusu - bezpecne deinit
            try:
                leds[n].deinit()
            except Exception:
                pass
        for n in LED_PINS:
            leds[n] = pwmio.PWMOut(gp(n), frequency=old_freq, duty_cycle=0, variable_frequency=False)
            apply_led(n)
        pwm_freq = old_freq


# --- Keep-alive setup (GP16) ---
print("[INIT] konfigurace keep-alive pinu na GPIO {} (LOW, vypnuto)...".format(KEEP_ALIVE_PIN))
ka_pin = digitalio.DigitalInOut(gp(KEEP_ALIVE_PIN))
ka_pin.direction = digitalio.Direction.OUTPUT
ka_pin.value = False
ka_enabled = False
ka_period_start = 0.0
ka_high_now = False
print("[INIT]   keep-alive pripraven (po bootu vypnuto).")

# --- DEBUG: onboard LED (GP25) zrcadli keep-alive signal ---------------------
# Pri rozsviceni KA signalu rozsvitime onboard LED, ale prodloužime na min 1 s
# (KA pulz je jen 400 ms - kratke na vsimnuti). Sekce se v produkci odebere.
DEBUG_LED_MIN_ON_S = 1.0
debug_led = digitalio.DigitalInOut(board.LED)
debug_led.direction = digitalio.Direction.OUTPUT
debug_led.value = False
debug_led_off_t = 0.0
print("[INIT]   onboard LED (DEBUG) zrcadli KA signal, min pulz {:.1f} s".format(DEBUG_LED_MIN_ON_S))


def keep_alive_tick(t):
    """Neblokujici keep-alive: kazdych 10 s pulz 400 ms HIGH.
    Soucasne zrcadli signal na onboard LED s prodlouzenim na min 1 s (DEBUG).
    """
    global ka_period_start, ka_high_now
    if not ka_enabled:
        if ka_high_now:
            ka_pin.value = False
            ka_high_now = False
        _debug_led_tick(t, ka_pulse_active=False)
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
    _debug_led_tick(t, ka_pulse_active=ka_high_now)


def _debug_led_tick(t, ka_pulse_active):
    """Onboard LED kopiruje KA, ale rozsviceni se prodluzuje na min DEBUG_LED_MIN_ON_S."""
    global debug_led_off_t
    if ka_pulse_active:
        if not debug_led.value:
            debug_led.value = True
        debug_led_off_t = t + DEBUG_LED_MIN_ON_S    # prubezne posouvame strop
    else:
        if debug_led.value and t >= debug_led_off_t:
            debug_led.value = False


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


# --- RozsvitJerab (SWITCH 2) -------------------------------------------------
# LED se rozsveci POSTUPNE v poradi (14, 15, 10, 0, 9, 13) - stejna sekvence
# jaka je v Init testu, jen bez YELLOW TOP (GPIO 1). Krok 100 ms mezi LED.
# Po 4 s OD ZAPNUTI POSLEDNI LED v sekvenci zacne YELLOW (GPIO 1) probliknuti:
# 3 s RED (GPIO 0) sviti / 300 ms YELLOW sviti (RED zhasla - exkluzivni par).
JERAB_SEQ = (14, 15, 10, 0, 9, 13)   # postupne rozsveceni, BEZ YELLOW TOP (1)
JERAB_TOP_PINS = (0, 1)               # RED, YELLOW (jen jeden najednou)

jerab_active = False
jerab_seq_idx = 0
jerab_last_step_t = 0.0
jerab_seq_done_t = 0.0     # cas zapnuti POSLEDNI LED v sekvenci (start odpoctu 4 s)
jerab_top_started = False
jerab_top_phase = 0        # 0 = RED svici, 1 = YELLOW svici
jerab_top_phase_t = 0.0


def jerab_on():
    """Spusti JERAB: postupne rozsveceni (14,15,10,0,9,13), YELLOW blikani 4s po posledni LED."""
    global jerab_active, jerab_seq_idx, jerab_last_step_t, jerab_seq_done_t
    global jerab_top_started, jerab_top_phase, jerab_top_phase_t
    if jerab_active:
        return
    jerab_active = True
    jerab_seq_idx = 0
    jerab_last_step_t = time.monotonic()
    jerab_seq_done_t = 0.0           # nastavi se az tick zapne posledni LED
    jerab_top_started = False
    jerab_top_phase = 0
    jerab_top_phase_t = 0.0
    # zhasit vsechny JERAB LED - sekvenci pak rozsvecuje tick
    for n in JERAB_PINS:
        set_led(n, False)
    print("[JERAB] RozsvitJerab START (sekvence {}, krok {} ms, YELLOW blikani 4s po posledni LED)".format(
        list(JERAB_SEQ), int(JERAB_STEP_S * 1000)))


def jerab_off():
    global jerab_active, jerab_top_started
    if not jerab_active:
        return
    jerab_active = False
    jerab_top_started = False
    for n in JERAB_PINS:
        set_led(n, False)
    print("[JERAB] RozsvitJerab STOP")


def jerab_tick(t):
    """Postupne rozsveceni sekvence (vc. GPIO 0) + YELLOW blikani 4 s po posledni LED."""
    global jerab_seq_idx, jerab_last_step_t, jerab_seq_done_t
    global jerab_top_started, jerab_top_phase, jerab_top_phase_t
    if not jerab_active:
        return
    # 1) postupne rozsveceni sekvence (14, 15, 10, 0, 9, 13)
    if jerab_seq_idx < len(JERAB_SEQ):
        if (t - jerab_last_step_t) >= JERAB_STEP_S:
            n = JERAB_SEQ[jerab_seq_idx]
            set_led(n, True)
            jerab_seq_idx += 1
            jerab_last_step_t = t
            if jerab_seq_idx == len(JERAB_SEQ):
                # posledni LED zapnuta - od tohoto okamziku ceka 4 s na zacatek YELLOW blikani
                jerab_seq_done_t = t
        return  # behem rozsveceni jeste nestartujeme blikani
    # 2) YELLOW probliknuti po 4 s od POSLEDNI LED (GPIO 0 uz sviti ze sekvence)
    if not jerab_top_started:
        if (t - jerab_seq_done_t) >= JERAB_TOP_BLINK_DELAY_S:
            jerab_top_started = True
            jerab_top_phase = 0          # 0 = RED on, 1 = YELLOW probliknuti
            jerab_top_phase_t = t
        return
    # cyklicke prepinani RED <-> YELLOW (exkluzivni par)
    hold = JERAB_TOP_RED_S if jerab_top_phase == 0 else JERAB_TOP_YELLOW_S
    if (t - jerab_top_phase_t) >= hold:
        jerab_top_phase = 1 - jerab_top_phase
        jerab_top_phase_t = t
        if jerab_top_phase == 0:
            set_led(JERAB_TOP_PINS[1], False)
            set_led(JERAB_TOP_PINS[0], True)
        else:
            set_led(JERAB_TOP_PINS[0], False)
            set_led(JERAB_TOP_PINS[1], True)


# --- PustAuto (SWITCH 5): semafor pro odjezd auta -----------------------------
# Fazovy stroj se 4 + 1 fazemi:
#   INIT      - rozsviti RED na semaforu + 1. OneWire pixel bilou
#   RUN_SEM   - klasicka semaforova sekvence skoncici u GREEN
#   GO        - bezici cara pres 12 OneWire pixelu, zrychluje, na konci zhasne
#   ODJETO    - zelena se klasicky vrati na cervenou
#   END       - vse zhasnuto, stroj se zastavi
# Tabulka casovych prodlev MEZI fazemi (z zadani: cas mezi koncem akce
# aktualni faze a startem dalsi faze):
PA_TRANSITION_S = {
    "INIT":    3.0,
    "RUN_SEM": 1.0,
    "GO":      3.0,
    "ODJETO":  3.0,
}
# Vnitrni casovani semafor sekvenci (sub-step v ramci faze):
PA_RUN_REDYELLOW_S = 1.0     # RED + YELLOW spolu (klasicka faze pred GREEN)
PA_OD_GREEN_HOLD_S = 1.5     # ODJETO: jak dlouho jeste GREEN po vstupu, pak YELLOW
PA_OD_YELLOW_S = 1.5         # ODJETO: YELLOW pred RED
# GO faze: 12 pixelu, doba na pixel klesa linearne (zrychluje):
PA_GO_PIX_FIRST_S = 0.45
PA_GO_PIX_LAST_S = 0.08

PA_RED_PIN = 3
PA_YELLOW_PIN = 2
PA_GREEN_PIN = 4

pa_active = False
pa_phase = None              # "INIT" | "RUN_SEM" | "GO" | "ODJETO" | "END"
pa_action_done = False       # True = animace faze probehla, cekame na prodlevu
pa_action_done_t = 0.0
# RUN_SEM sub-state
pa_run_sub = 0
pa_run_sub_t = 0.0
# GO sub-state
pa_go_pixel = 0              # 0..N_ONEWIRE_PIXELS  (N = pri vystupu)
pa_go_pix_start_t = 0.0
# ODJETO sub-state
pa_od_sub = 0
pa_od_sub_t = 0.0


def _pa_clear_semafor():
    for n in (PA_RED_PIN, PA_YELLOW_PIN, PA_GREEN_PIN):
        set_led(n, False)


def _pa_clear_onewire():
    onewire.fill((0, 0, 0))
    onewire.show()


def _pa_enter_init(t):
    global pa_phase, pa_action_done, pa_action_done_t
    pa_phase = "INIT"
    _pa_clear_semafor()
    _pa_clear_onewire()
    set_led(PA_RED_PIN, True)
    onewire[0] = (255, 255, 255)
    onewire.show()
    pa_action_done = True   # INIT je staticka akce - okamzite hotova, jen cekame na prodlevu
    pa_action_done_t = t
    print("[AUTO] INIT (RED + OneWire[0] WHITE) -> prodleva {:.1f} s".format(PA_TRANSITION_S["INIT"]))


def _pa_enter_run_sem(t):
    global pa_phase, pa_action_done, pa_run_sub, pa_run_sub_t
    pa_phase = "RUN_SEM"
    # OneWire[0] nechame svitit (z INIT) - bude pokracovat do zacatku GO faze.
    # Zacatek: RED uz sviti z INIT. Sub-step 0 = pridat YELLOW po PA_RUN_REDYELLOW_S
    pa_run_sub = 0
    pa_run_sub_t = t
    pa_action_done = False
    set_led(PA_RED_PIN, True)
    set_led(PA_YELLOW_PIN, False)
    set_led(PA_GREEN_PIN, False)
    print("[AUTO] RUN_SEM start (RED -> RED+YELLOW -> GREEN, OneWire[0] sviti dal)")


def _pa_tick_run_sem(t):
    """Sub-stroj RUN_SEM. Sub-state:
       0 = RED sviti, cekame PA_RUN_REDYELLOW_S, pak pridame YELLOW
       1 = RED+YELLOW sviti, cekame PA_RUN_REDYELLOW_S, pak GREEN (zhasni RED+YELLOW)
       2 = GREEN sviti -> akce hotova
    """
    global pa_run_sub, pa_run_sub_t, pa_action_done, pa_action_done_t
    if pa_run_sub == 0:
        if (t - pa_run_sub_t) >= PA_RUN_REDYELLOW_S:
            set_led(PA_YELLOW_PIN, True)
            pa_run_sub = 1
            pa_run_sub_t = t
            print("[AUTO] RUN_SEM: RED+YELLOW")
    elif pa_run_sub == 1:
        if (t - pa_run_sub_t) >= PA_RUN_REDYELLOW_S:
            set_led(PA_RED_PIN, False)
            set_led(PA_YELLOW_PIN, False)
            set_led(PA_GREEN_PIN, True)
            pa_run_sub = 2
            pa_action_done = True
            pa_action_done_t = t
            print("[AUTO] RUN_SEM: GREEN (action done, prodleva {:.1f} s)".format(PA_TRANSITION_S["RUN_SEM"]))


def _pa_enter_go(t):
    global pa_phase, pa_action_done, pa_go_pixel, pa_go_pix_start_t
    pa_phase = "GO"
    # OneWire[0] uz sviti (z INIT/RUN_SEM) - na nej navazeme fade-out + fade-in[1].
    # Ostatni pixely jsou jiz zhasnute, neresetujeme.
    pa_go_pixel = 0
    pa_go_pix_start_t = t
    pa_action_done = False
    # GREEN zustava svitit - "zustane svitit zelena" + cara probehne
    print("[AUTO] GO start (bezici cara z OneWire[0], zrychluje, {} -> {} s/pixel)".format(
        PA_GO_PIX_FIRST_S, PA_GO_PIX_LAST_S))


def _go_pixel_duration(i):
    """Doba na i-ty prechod (0..N-1). Linearni interpolace mezi FIRST a LAST."""
    n = N_ONEWIRE_PIXELS - 1   # delimo poctem prechodu
    if n <= 0:
        return PA_GO_PIX_FIRST_S
    frac = i / n
    return PA_GO_PIX_FIRST_S + (PA_GO_PIX_LAST_S - PA_GO_PIX_FIRST_S) * frac


def _pa_tick_go(t):
    """Bezici cara: pixel i fade-out, pixel i+1 fade-in.
       Po dojeti k poslednimu fade-out a hotovo.
    """
    global pa_go_pixel, pa_go_pix_start_t, pa_action_done, pa_action_done_t
    if pa_go_pixel >= N_ONEWIRE_PIXELS:
        return  # uz hotovo
    dur = _go_pixel_duration(pa_go_pixel)
    progress = (t - pa_go_pix_start_t) / dur
    if progress >= 1.0:
        progress = 1.0
    # aktualni pixel klesa, dalsi stoupa (pokud existuje)
    cur = pa_go_pixel
    nxt = cur + 1
    bri_cur = 1.0 - progress
    bri_nxt = progress
    onewire[cur] = (int(255 * bri_cur), int(255 * bri_cur), int(255 * bri_cur))
    if nxt < N_ONEWIRE_PIXELS:
        onewire[nxt] = (int(255 * bri_nxt), int(255 * bri_nxt), int(255 * bri_nxt))
    onewire.show()
    if progress >= 1.0:
        # konec aktualniho prechodu - aktualni pixel je vypnuty
        onewire[cur] = (0, 0, 0)
        onewire.show()
        pa_go_pixel = nxt
        pa_go_pix_start_t = t
        if pa_go_pixel >= N_ONEWIRE_PIXELS:
            # uplne hotovo
            _pa_clear_onewire()
            pa_action_done = True
            pa_action_done_t = t
            print("[AUTO] GO: hotovo (prodleva {:.1f} s)".format(PA_TRANSITION_S["GO"]))


def _pa_enter_odjeto(t):
    global pa_phase, pa_action_done, pa_od_sub, pa_od_sub_t
    pa_phase = "ODJETO"
    pa_od_sub = 0
    pa_od_sub_t = t
    pa_action_done = False
    # GREEN sviti (z GO faze). Stavy: 0 = GREEN hold, 1 = YELLOW, 2 = RED (hotovo)
    set_led(PA_GREEN_PIN, True)
    set_led(PA_YELLOW_PIN, False)
    set_led(PA_RED_PIN, False)
    print("[AUTO] ODJETO start (GREEN -> YELLOW -> RED)")


def _pa_tick_odjeto(t):
    global pa_od_sub, pa_od_sub_t
    global pa_action_done, pa_action_done_t
    if pa_od_sub == 0:
        # GREEN sviti, pak prepnout na YELLOW
        if (t - pa_od_sub_t) >= PA_OD_GREEN_HOLD_S:
            set_led(PA_GREEN_PIN, False)
            set_led(PA_YELLOW_PIN, True)
            pa_od_sub = 1
            pa_od_sub_t = t
            print("[AUTO] ODJETO: YELLOW")
    elif pa_od_sub == 1:
        # YELLOW sviti, pak prepnout na RED
        if (t - pa_od_sub_t) >= PA_OD_YELLOW_S:
            set_led(PA_YELLOW_PIN, False)
            set_led(PA_RED_PIN, True)
            pa_od_sub = 2
            pa_action_done = True
            pa_action_done_t = t
            print("[AUTO] ODJETO: RED (action done, prodleva {:.1f} s)".format(PA_TRANSITION_S["ODJETO"]))


def _pa_enter_end(t):
    global pa_phase, pa_active
    pa_phase = "END"
    _pa_clear_semafor()
    _pa_clear_onewire()
    pa_active = False
    # END -> vabeniKoristi se zapne s prodlevou (dle zadani ~4 s)
    vabeni_arm_now(t + VABENI_POST_AUTO_DELAY_S)
    print("[AUTO] END - PustAuto dokonceno, vabeniKoristi za {:.1f} s".format(
        VABENI_POST_AUTO_DELAY_S))


def pustauto_start():
    global pa_active
    if pa_active:
        return
    pa_active = True
    vabeni_stop()                       # vabeniKoristi se deaktivuje pri startu PustAuto
    _pa_enter_init(time.monotonic())


def pustauto_off():
    """Hard stop (napr. interrupt z REPL; SW4 je momentova, neresetuje normalne)."""
    global pa_active, pa_phase
    if not pa_active and pa_phase != "END":
        return
    pa_active = False
    pa_phase = None
    _pa_clear_semafor()
    _pa_clear_onewire()
    vabeni_arm_now(time.monotonic())    # po preruseni take obnovit vabeniKoristi
    print("[AUTO] PustAuto preruseno (vabeniKoristi obnoveno)")


def pustauto_tick(t):
    """Driver fazoveho stroje. Bezi animaci aktualni faze nebo ceka na
    prodlevu mezi fazemi, pak prejde do dalsi faze."""
    global pa_action_done
    if not pa_active:
        return
    # 1) bezi animace faze?
    if not pa_action_done:
        if pa_phase == "RUN_SEM":
            _pa_tick_run_sem(t)
        elif pa_phase == "GO":
            _pa_tick_go(t)
        elif pa_phase == "ODJETO":
            _pa_tick_odjeto(t)
        # INIT je staticky (pa_action_done = True hned po enter)
        return
    # 2) akce hotova, cekame prodlevu, pak prechod
    transition = PA_TRANSITION_S.get(pa_phase, 0.0)
    if (t - pa_action_done_t) < transition:
        return
    # prechod do dalsi faze
    if pa_phase == "INIT":
        _pa_enter_run_sem(t)
    elif pa_phase == "RUN_SEM":
        _pa_enter_go(t)
    elif pa_phase == "GO":
        _pa_enter_odjeto(t)
    elif pa_phase == "ODJETO":
        _pa_enter_end(t)
    # END -> nic, pa_active je False


# --- MajakBuldozer (SWITCH 1 / REPL 'B') -------------------------------------
# Pulzovani jako majak stavebniho auta: pomale stoupani 0->MAX, kratky vrchol,
# pomaly pokles zpet na 0. Realizovano fci sin(pi*phase)^N: vyssi N = uzsi
# vrchol a delsi "tmavy" cas v periode.
# Vrchol je PWM_MAX_PCT[BULDOZER_LED_PIN] (= 65 % dle tabulky).
BULDOZER_LED_PIN = 7
BULDOZER_PERIOD_S = 2.0       # delka jedne periody pulzu
BULDOZER_SHARPNESS = 6        # N v sin^N - vyssi = uzsi peak (rozumne 4..10)

bul_active = False
bul_start = 0.0


def buldozer_start():
    global bul_active, bul_start
    if bul_active:
        print("[BULDOZER] uz pulzuje")
        return
    bul_active = True
    bul_start = time.monotonic()
    led_on[BULDOZER_LED_PIN] = True   # apply_led pak ridi viditelnou intenzitu pres duty
    print("[BULDOZER] MajakBuldozer ZAPNUTO (perioda {:.1f} s, peak {} %)".format(
        BULDOZER_PERIOD_S, PWM_MAX_PCT[BULDOZER_LED_PIN]))


def buldozer_off():
    global bul_active
    if not bul_active:
        return
    bul_active = False
    led_duty_pct[BULDOZER_LED_PIN] = PWM_MAX_PCT[BULDOZER_LED_PIN]  # vrat default
    set_led(BULDOZER_LED_PIN, False)
    print("[BULDOZER] MajakBuldozer VYPNUTO")


def buldozer_tick(t):
    """Spocte aktualni duty pro BULDOZER LED a zapise jen kdyz se zmenila."""
    if not bul_active:
        return
    phase = ((t - bul_start) % BULDOZER_PERIOD_S) / BULDOZER_PERIOD_S  # 0..1
    shape = math.sin(math.pi * phase) ** BULDOZER_SHARPNESS             # 0..1, uzky peak v 0.5
    peak = PWM_MAX_PCT[BULDOZER_LED_PIN]
    new_pct = int(round(shape * peak))
    if new_pct != led_duty_pct[BULDOZER_LED_PIN]:
        led_duty_pct[BULDOZER_LED_PIN] = new_pct
        apply_led(BULDOZER_LED_PIN)


# --- PozorStavba (auto, bezi od bootu) ---------------------------------------
# Bliknuti dvou cervenych LED ve skupine POZOR (GPIO 5, 6) tak, aby alternovaly
# - klasicky stavebni "varovny" semafor. Pulperioda = POZOR_HALF_PERIOD_S.
# Pauza: manualni toggle 5 nebo 6 z REPL pozastavi blikani (uzivatel chce
# kontrolovat stav). REPL 'X' znovu zapne.
pozor_running = True       # vychozi stav po bootu
pozor_paused = False
pozor_phase = 0            # 0 -> sviti pin 5, 1 -> sviti pin 6
pozor_last_t = 0.0


def pozor_pause(reason=""):
    global pozor_paused
    if pozor_paused:
        return
    pozor_paused = True
    extra = " ({})".format(reason) if reason else ""
    print("[POZOR] PozorStavba PAUZA{} - obnoveni: 'X'".format(extra))


def pozor_resume():
    global pozor_paused, pozor_last_t, pozor_phase
    if not pozor_paused and pozor_running:
        print("[POZOR] PozorStavba uz bezi")
        return
    pozor_paused = False
    pozor_last_t = time.monotonic()
    pozor_phase = 0
    set_led(POZOR_PINS[0], True)
    set_led(POZOR_PINS[1], False)
    print("[POZOR] PozorStavba ZAPNUTO")


def pozor_tick(t):
    global pozor_phase, pozor_last_t
    if not pozor_running or pozor_paused:
        return
    if (t - pozor_last_t) >= POZOR_HALF_PERIOD_S:
        pozor_phase = 1 - pozor_phase
        if pozor_phase == 0:
            set_led(POZOR_PINS[1], False)
            set_led(POZOR_PINS[0], True)
        else:
            set_led(POZOR_PINS[0], False)
            set_led(POZOR_PINS[1], True)
        pozor_last_t = t


# --- RozsvitStavbu (SWITCH 3) ------------------------------------------------
# Triviální: rozsviti STAVBA (GPIO 12) + MICHACKA (GPIO 8) zaroven.
def stavba_on():
    set_led(STAVBA_LED_PIN, True)
    set_led(MICHACKA_LED_PIN, True)
    print("[STAVBA] RozsvitStavbu ZAPNUTO (GPIO {} + {})".format(STAVBA_LED_PIN, MICHACKA_LED_PIN))


def stavba_off():
    set_led(STAVBA_LED_PIN, False)
    set_led(MICHACKA_LED_PIN, False)
    print("[STAVBA] RozsvitStavbu VYPNUTO")


# --- vabeniKoristi (TLACITKO, GPIO 11) ---------------------------------------
# Svetlo pro TLACITKO pulzuje, aby pritahlo pozornost. Spousti se asi 5 s po
# nabehnuti programu HRA. Pri startu PustAuto se vypne, po END fazi PustAuto
# se znovu zapne (s nulovou prodlevou - okamzite).
# Pulzni profil: smooth sin(pi*phase)^2 - jemne pulzuje 0 -> MAX -> 0.
vabeni_active = False           # True = prave pulzuje
vabeni_should_run = True        # True = bude se spoustet po uplynuti delay
vabeni_next_start_t = 0.0       # cas kdy ma zacit pulzovat (auto-start logika)
vabeni_pulse_start_t = 0.0      # cas startu aktualniho pulzovani


def vabeni_arm_now(t):
    """Naplanuje vabeni na okamzite zapnuti (po END PustAuto)."""
    global vabeni_should_run, vabeni_next_start_t
    vabeni_should_run = True
    vabeni_next_start_t = t


def vabeni_arm_boot(t):
    """Naplanuje vabeni na zapnuti za VABENI_BOOT_DELAY_S (po startu HRA)."""
    global vabeni_should_run, vabeni_next_start_t
    vabeni_should_run = True
    vabeni_next_start_t = t + VABENI_BOOT_DELAY_S


def vabeni_start(t):
    global vabeni_active, vabeni_pulse_start_t
    if vabeni_active:
        return
    vabeni_active = True
    vabeni_pulse_start_t = t
    led_on[VABENI_LED_PIN] = True   # apply_led pak ridi viditelnou intenzitu pres duty
    print("[VABENI] vabeniKoristi START (GPIO {}, max {} %)".format(
        VABENI_LED_PIN, VABENI_MAX_PCT))


def vabeni_stop():
    """Vypne pulzovani a oznaci ze se nema spustit (dokud nekdo nevola vabeni_arm_*)."""
    global vabeni_active, vabeni_should_run
    vabeni_active = False
    vabeni_should_run = False
    led_duty_pct[VABENI_LED_PIN] = PWM_MAX_PCT[VABENI_LED_PIN]   # vrat default
    set_led(VABENI_LED_PIN, False)
    print("[VABENI] vabeniKoristi STOP")


def vabeni_tick(t):
    """Auto-start po prodleve + pulzni animace."""
    global vabeni_active, vabeni_pulse_start_t
    # 1) auto-start po prodleve
    if not vabeni_active and vabeni_should_run and t >= vabeni_next_start_t:
        vabeni_start(t)
    # 2) pulzni animace
    if not vabeni_active:
        return
    phase = ((t - vabeni_pulse_start_t) % VABENI_PERIOD_S) / VABENI_PERIOD_S  # 0..1
    shape = math.sin(math.pi * phase) ** 2                                    # 0..1, smooth
    new_pct = int(round(shape * VABENI_MAX_PCT))
    if new_pct != led_duty_pct[VABENI_LED_PIN]:
        led_duty_pct[VABENI_LED_PIN] = new_pct
        apply_led(VABENI_LED_PIN)


# --- sleepBox / ShutDown (System sekce v zadani) -----------------------------
# sleepBox: po SLEEP_BOX_TIMEOUT_S necinnosti fyzickych vstupu (GPIO 18-22)
#           vypne vsechny vystupy a zastavi HRA. Keep-alive bezi dal. REPL
#           se do necinnosti nezapocitava.
# ShutDown: po SHUTDOWN_TIMEOUT_S v rezimu sleepBox vypne keep-alive trvale -
#           HW odrizne napajeni a system koncti (smrt, navrat jen pres boot).
sleepbox_active = False
sleepbox_entered_t = 0.0      # cas vstupu do sleepBox (pro ShutDown timer)
last_input_t = 0.0            # cas posledni zmeny fyzickeho vstupu


def notify_input_activity(t):
    """Vola se pri kazde debounced zmene fyzickeho switche.
    Resetuje sleepBox timer; pokud sleepBox aktivni, probudi system."""
    global last_input_t
    last_input_t = t
    if sleepbox_active:
        sleepbox_exit(t)


def sleepbox_enter(t):
    """Vstup do sleepBox: vypne vsechny vystupy + zastavi HRA. KA bezi dal."""
    global sleepbox_active, sleepbox_entered_t, pozor_running
    if sleepbox_active:
        return
    sleepbox_active = True
    sleepbox_entered_t = t
    # zastav vsechny HRA funkce
    buldozer_off()
    jerab_off()
    stavba_off()
    pustauto_off()
    vabeni_stop()
    pozor_running = False
    # zhasit vsechny LED (PWM 0-15 + OneWire pasek)
    for n in LED_PINS:
        set_led(n, False)
    onewire.fill((0, 0, 0))
    onewire.show()
    print("[SLEEP] sleepBox AKTIVOVAN (vse OFF, KA bezi dal, ShutDown za {:.0f} s)".format(
        SHUTDOWN_TIMEOUT_S))


def sleepbox_exit(t):
    """Probuzeni ze sleepBox - HRA do defaultniho stavu."""
    global sleepbox_active, pozor_running, pozor_paused, pozor_last_t, pozor_phase
    if not sleepbox_active:
        return
    sleepbox_active = False
    # default HRA stav: PozorStavba bezi, vabeniKoristi naplanovany za VABENI_BOOT_DELAY_S
    pozor_running = True
    pozor_paused = False
    pozor_last_t = t
    pozor_phase = 0
    set_led(POZOR_PINS[0], True)
    set_led(POZOR_PINS[1], False)
    vabeni_arm_boot(t)
    print("[SLEEP] sleepBox DEAKTIVOVAN - HRA v default stavu (PozorStavba + vabeni za {:.0f} s)".format(
        VABENI_BOOT_DELAY_S))


def sleepbox_tick(t):
    """Sleduje necinnost vstupu, po timeoutu vstoupi do sleepBox."""
    if sleepbox_active:
        return
    if (t - last_input_t) >= SLEEP_BOX_TIMEOUT_S:
        sleepbox_enter(t)


def shutdown_tick(t):
    """V sleepBox: po SHUTDOWN_TIMEOUT_S vypne keep-alive a ukonci system."""
    if not sleepbox_active:
        return
    if (t - sleepbox_entered_t) >= SHUTDOWN_TIMEOUT_S:
        shutdown_now()


def shutdown_now():
    """Trvale vypnuti: KA OFF -> HW odrizne napajeni. Pokud lze, deep sleep."""
    keep_alive_off()
    debug_led.value = False
    print("=" * 50)
    print("[SHUTDOWN] SHUTDOWN_TIMEOUT_S vyprsel - keep-alive OFF, system konci")
    print("=" * 50)
    # Pokus o deep sleep - sniz spotrebu nez HW odrizne napajeni.
    # Pokud alarm modul neni dostupny (CircuitPython build), busy-wait do odpojeni.
    try:
        import alarm
        alarm.exit_and_deep_sleep_until_alarms()
    except Exception as e:
        print("[SHUTDOWN] deep sleep nedostupny ({}), busy-wait dokud HW neodpoji napajeni".format(e))
    while True:
        time.sleep(1.0)


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


# --- 1-wire LED setup (GP17, 12x WS2812 / Inolux IN-PI55) ---
ONEWIRE_BRIGHTNESS = 0.08    # 8 % (dle tabulky LED, AUTO RGB)
print("[INIT] inicializace 1-wire LED ({}x WS2812 na GPIO {})...".format(N_ONEWIRE_PIXELS, ONEWIRE_PIN))
# pixel_order=GRB je default WS2812 - Inolux IN-PI55 ma stejne poradi
onewire = neopixel.NeoPixel(
    gp(ONEWIRE_PIN), N_ONEWIRE_PIXELS,
    brightness=ONEWIRE_BRIGHTNESS, auto_write=False, pixel_order=neopixel.GRB,
)
onewire.fill((0, 0, 0))
onewire.show()
print("[INIT]   1-wire LED zhasnuty (brightness={}, pixel_order=GRB).".format(ONEWIRE_BRIGHTNESS))


def onewire_smoke_test():
    """RGB diagnosticky test - rozsviti cely retez R, G, B postupne, kazdou barvu 1 s.
    - kdyz nic nesviti: HW (napajeni, datalinka, prvni pixel mrtvy)
    - kdyz sviti spatne barvy: pixel_order (GRB vs RGB vs BRG vs ...)
    - kdyz se zastavi po N pixelech: vadny N+1 pixel nebo spojeni za nim
    """
    print("[1WIRE] smoke test - RED celym retezem na 1 s...")
    onewire.fill((255, 0, 0))
    onewire.show()
    time.sleep(1.0)
    print("[1WIRE] smoke test - GREEN celym retezem na 1 s...")
    onewire.fill((0, 255, 0))
    onewire.show()
    time.sleep(1.0)
    print("[1WIRE] smoke test - BLUE celym retezem na 1 s...")
    onewire.fill((0, 0, 255))
    onewire.show()
    time.sleep(1.0)
    onewire.fill((0, 0, 0))
    onewire.show()


def onewire_sequence_test(color=(0, 255, 0), step_s=0.4):
    """Postupne rozsviceni a zhasnuti pixel po pixelu - dle zadani."""
    onewire.fill((0, 0, 0))
    onewire.show()
    for i in range(N_ONEWIRE_PIXELS):
        onewire[i] = color
        onewire.show()
        print("[1WIRE]   pixel {:2d} ON  {}".format(i, color))
        time.sleep(step_s)
    time.sleep(step_s)
    for i in range(N_ONEWIRE_PIXELS):
        onewire[i] = (0, 0, 0)
        onewire.show()
        print("[1WIRE]   pixel {:2d} OFF".format(i))
        time.sleep(step_s)


def onewire_chase(color=(0, 255, 0), step_s=0.04):
    """Bezici pixel: rozsviti dalsi a zaroven zhasne predchozi (jen 1 sviti)."""
    onewire.fill((0, 0, 0))
    onewire.show()
    for i in range(N_ONEWIRE_PIXELS):
        onewire[i] = color
        if i > 0:
            onewire[i - 1] = (0, 0, 0)
        onewire.show()           # oba zapis projdou v jednom snimku
        print("[1WIRE]   pixel {:2d} {}".format(i, color))
        time.sleep(step_s)
    # zhasni i posledni
    onewire[N_ONEWIRE_PIXELS - 1] = (0, 0, 0)
    onewire.show()


# --- Init test: probliknuti LED po skupinach, v ramci skupiny LED po LED ---
LED_TEST_ON_S = 0.1     # doba sviceni jedne LED v init testu

print("[INIT] Test LED po skupinach (LED po LED)...")
time.sleep(0.5)  # kratka pauza, at je videt cisty start
for name, pins in LED_GROUPS:
    print("[INIT]   skupina {:8s} -> GPIO {}".format(name, list(pins)))
    for n in pins:
        set_led(n, True)
        time.sleep(LED_TEST_ON_S)
        set_led(n, False)
print("[INIT] Test LED hotov - vsechny LED OFF.")

print("[INIT] Test 1-wire LED - bezici pixel zelenou...")
onewire_chase(color=(0, 255, 0), step_s=0.04)
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

# Keep-alive je dle zadani sekce "System" automaticky zapnuty na pozadi.
print("[INIT] zapinam keep-alive natvrdo (HRA mode - bezi na pozadi)")
keep_alive_on()

# PozorStavba se spousti automaticky po bootu (zadani sekce "Pozor Stavba").
print("[INIT] spoustim PozorStavba (alternujici 5/6, perioda {} ms)".format(int(POZOR_HALF_PERIOD_S * 2 * 1000)))
pozor_last_t = time.monotonic()
set_led(POZOR_PINS[0], True)   # zacni RED LEFT svitici, RIGHT zhasnutou
set_led(POZOR_PINS[1], False)

# vabeniKoristi - naplanuj auto-start 5 s po startu HRA (zde je start HRA).
vabeni_arm_boot(time.monotonic())
print("[INIT] vabeniKoristi armed - start za {} s (GPIO {}, max {} %)".format(
    VABENI_BOOT_DELAY_S, VABENI_LED_PIN, VABENI_MAX_PCT))

# sleepBox timer - resetuj na start HRA (necinnost se pocita az od ted).
last_input_t = time.monotonic()
print("[INIT] sleepBox timer armed (timeout {:.0f} s, pak ShutDown za dalsich {:.0f} s)".format(
    SLEEP_BOX_TIMEOUT_S, SHUTDOWN_TIMEOUT_S))

# Switche srovnane podle fyzicke polohy (aktivni LOW).
if confirmed[SW1_BULDOZER_PIN] is False:
    print("[INIT]   SWITCH 1 sepnut -> spoustim MajakBuldozer")
    buldozer_start()
if confirmed[SW2_JERAB_PIN] is False:
    print("[INIT]   SWITCH 2 sepnut -> spoustim RozsvitJerab")
    jerab_on()
if confirmed[SW3_STAVBA_PIN] is False:
    print("[INIT]   SWITCH 3 sepnut -> spoustim RozsvitStavbu")
    stavba_on()
if confirmed[SW4_AUTO_PIN] is False:
    # SW4 je momentova - pokud je pri bootu sepnuta, spustime PustAuto a uz neresetujeme
    print("[INIT]   SWITCH 4 sepnut (momentova) -> spoustim PustAuto")
    pustauto_start()
if confirmed[SW5_ALL_PIN] is False:
    print("[INIT]   SWITCH 5 sepnut -> zapinam vsechny LED")
    all_leds_on()


def print_help():
    print("-" * 50)
    print("Prikazy (jednim znakem, bez Enteru):")
    print("  0..9 a..f  -> toggle LED GPIO 0..15 (hex)")
    print("                (toggle 5/6 pauzuje PozorStavba, obnoveni 'X')")
    print("  A          -> vsechny LED ON (GPIO {}/{} alternuji {:.1f}s)".format(
        EXCLUSIVE_PAIR[0], EXCLUSIVE_PAIR[1], ALT_PERIOD_S))
    print("  Z          -> vsechny LED OFF")
    print("  S          -> stav LED (vypis svitici)")
    print("  W          -> zapnout keep-alive signal")
    print("  Woff       -> vypnout keep-alive signal")
    print("  N          -> opakovat 1-wire LED test (R/G/B + sekvence)")
    print("  B          -> toggle MajakBuldozer (GPIO {}, peak {}%)".format(
        BULDOZER_LED_PIN, PWM_MAX_PCT[BULDOZER_LED_PIN]))
    print("  X          -> obnovit PozorStavba (po manualnim toggle 5/6)")
    print("  D<n>       -> PWM duty 0..100 % pro VSECHNY LED  (napr. D50, ukonci Enter)")
    print("                kazda LED clamped na sve PWM_MAX (viz 'P' / tabulka)")
    print("  P<hex>=<n> -> PWM duty pro JEDNU LED + zapnout  (napr. Pa=30)")
    print("                clamped na PWM_MAX_PCT[n] z tabulky")
    print("  + / -      -> +/- {} % duty na posledni LED z 'P'  (bez Enteru)".format(DUTY_STEP_PCT))
    print("  P          -> vypis duty + PWM_MAX vsech LED")
    print("  F<n>       -> PWM freq v Hz      (napr. F1000, ukonci Enter)")
    print("                rozsah {}..{} Hz (frekvence je sdilena vsemi LED)".format(PWM_FREQ_MIN, PWM_FREQ_MAX))
    print("  ?          -> tato napoveda")
    print("HRA - mapovani switchu:")
    print("  SW1 (GPIO {})  MajakBuldozer".format(SW1_BULDOZER_PIN))
    print("  SW2 (GPIO {})  RozsvitJerab".format(SW2_JERAB_PIN))
    print("  SW3 (GPIO {})  RozsvitStavbu".format(SW3_STAVBA_PIN))
    print("  SW4 (GPIO {})  PustAuto (momentova, dobehne)".format(SW4_AUTO_PIN))
    print("  SW5 (GPIO {})  vsechny LED".format(SW5_ALL_PIN))
    print("Auto na pozadi:")
    print("  PozorStavba (GPIO {}/{} alternuji)".format(POZOR_PINS[0], POZOR_PINS[1]))
    print("  vabeniKoristi (GPIO {}, pulzuje, vyp behem PustAuto)".format(VABENI_LED_PIN))
    print("Aktualni PWM: freq={} Hz  (per-LED duty - viz 'P' nebo 'S')".format(pwm_freq))
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
            # Manualni toggle LED ve skupine POZOR pauzuje PozorStavba
            if n in POZOR_PINS and pozor_running and not pozor_paused:
                pozor_pause("manualni toggle GPIO {}".format(n))
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
            if svici:
                print("[LED] svici GPIO:")
                for n in svici:
                    print("       GPIO {:2d} @ {:3d}%".format(n, led_duty_pct[n]))
            else:
                print("[LED] zadne LED nesviti")
            return
        if ch == "?":
            print_help()
            return
        if ch == "W":
            keep_alive_on()
            return
        if ch == "N":
            print("[1WIRE] manualni test 1-wire LED...")
            onewire_smoke_test()
            onewire_sequence_test(color=(0, 255, 0), step_s=0.4)
            print("[1WIRE] hotovo.")
            return
        if ch == "B":
            if bul_active:
                buldozer_off()
            else:
                buldozer_start()
            return
        if ch == "X":
            pozor_resume()
            return
        if ch == "+":
            nudge_last_led(+DUTY_STEP_PCT)
            return
        if ch == "-":
            nudge_last_led(-DUTY_STEP_PCT)
            return
        print("[!] neznamy znak: {!r}  (? = napoveda)".format(ch))
        return
    if tok == "Woff":
        keep_alive_off()
        return
    if tok == "D":
        duties = [led_duty_pct[n] for n in LED_PINS]
        if min(duties) == max(duties):
            print("[PWM] vsechny LED duty = {}%".format(duties[0]))
        else:
            print("[PWM] duty se lisi: min={}%, max={}%  (vypis vsech: 'P')".format(min(duties), max(duties)))
        return
    if tok == "F":
        print("[PWM] aktualni frekvence = {} Hz".format(pwm_freq))
        return
    if tok == "P":
        print_all_duties()
        return
    if tok[0] == "D" and len(tok) > 1 and tok[1:].isdigit():
        set_pwm_duty_all(int(tok[1:]))
        return
    if tok[0] == "F" and len(tok) > 1 and tok[1:].isdigit():
        set_pwm_freq(int(tok[1:]))
        return
    # Per-LED duty:  P<hex>=<n>   napr.  Pa=30  (LED 10 na 30 %)
    if (tok[0] == "P" and len(tok) >= 4
            and tok[1] in HEX_DIGITS and tok[2] == "="
            and tok[3:].isdigit()):
        set_led_duty(int(tok[1], 16), int(tok[3:]))
        return
    print("[!] neznamy prikaz: {!r}  (? = napoveda)".format(tok))


# Stav pro vstupni parser - kvuli viceznakovemu "Woff"
input_buffer = ""
last_char_t = 0.0
W_TIMEOUT_S = 0.25  # po teto dobe se osamocene "W" vyhodnoti jako zapnuti KA


def _echo(s):
    """Echo na seriak (bez bufferingu, bez konverze \\n -> \\r\\n)."""
    sys.stdout.write(s)


def feed_char(ch, t):
    """Akumuluje znaky, echuje je zpet uzivateli a vyhodnocuje.
    Whitespace (Enter/space/tab) = flush. W, D, F, P startuji buffer mod.
    Woff se rozezna automaticky, D/F/P cekaji na Enter. Backspace maze v bufferu."""
    global input_buffer

    # Enter / space / tab -> echo CRLF + flush buffer
    if ch in ("\r", "\n", " ", "\t"):
        _echo("\r\n")
        if input_buffer:
            handle_token(input_buffer)
            input_buffer = ""
        return

    # Backspace / DEL -> smaze posledni znak v bufferu a v konzoli
    if ch in ("\x08", "\x7f"):
        if input_buffer:
            input_buffer = input_buffer[:-1]
            _echo("\b \b")
        return

    # Echo jen tisknutelnych ASCII znaku (control chars ignoruj)
    if " " < ch <= "~":
        _echo(ch)
    else:
        return

    if input_buffer:
        input_buffer += ch
        if input_buffer == "Woff":
            _echo("\r\n")
            handle_token(input_buffer)
            input_buffer = ""
            return
        if len(input_buffer) >= 12:  # bezpecnostni strop
            _echo("\r\n")
            handle_token(input_buffer)
            input_buffer = ""
        return
    if ch in ("W", "D", "F", "P"):
        input_buffer = ch
        return
    # Jednoznakovy prikaz -> odradkuj pred odpovedi
    _echo("\r\n")
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
            sys.stdout.write("\r\n")
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
            # Resetuj sleepBox timer; pokud sleepBox bezi, probud system.
            was_sleeping = sleepbox_active
            notify_input_activity(t)
            if was_sleeping:
                # Probuzeni - HRA reakci na tento stisk neaplikujeme (zadani: default stav).
                continue
            # HRA mapovani switchu:
            if n == SW1_BULDOZER_PIN:
                if v is False:
                    buldozer_start()
                else:
                    buldozer_off()
            elif n == SW2_JERAB_PIN:
                if v is False:
                    jerab_on()
                else:
                    jerab_off()
            elif n == SW3_STAVBA_PIN:
                if v is False:
                    stavba_on()
                else:
                    stavba_off()
            elif n == SW4_AUTO_PIN:
                # SW4 je momentova (OFF-(ON)). Stisk -> spusti PustAuto,
                # uvolneni ignorujeme - funkce dobehne dokonce (do END faze).
                if v is False:
                    pustauto_start()
                # else: pustime PustAuto bezet az do END
            elif n == SW5_ALL_PIN:
                if v is False:
                    all_leds_on()
                else:
                    all_leds_off()

    # Keep-alive a sleep/shutdown logika bezi vzdy (i v sleepBox rezimu).
    keep_alive_tick(t)
    sleepbox_tick(t)
    shutdown_tick(t)

    # HRA ticky bezi jen kdyz nejsme v sleepBox (sleepBox vse zhasl).
    if not sleepbox_active:
        alt_tick(t)
        pozor_tick(t)
        jerab_tick(t)
        buldozer_tick(t)
        vabeni_tick(t)
        pustauto_tick(t)

    time.sleep(0.005)
