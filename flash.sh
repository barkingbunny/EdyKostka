#!/usr/bin/env bash
# flash.sh - nahraj soubor na pripojenou CIRCUITPY desku (Raspberry Pi Pico).
#
# Pouziti:
#   sh flash.sh            # nahraje code.py
#   sh flash.sh boot.py    # nahraje jiny soubor
#   sh flash.sh code.py lib/foo.py   # nahraje vice souboru
#
# Skript overi, ze je CIRCUITPY pripojeny a zapisovatelny, zkopiruje
# soubor(y) a zavola sync (jinak Linux drzi zapis v cache a deska to
# nedostane / muze se to porusit pri replug).

set -u

DEST="/run/media/jakub/CIRCUITPY"

# Pokud nejsou zadne argumenty, default = code.py
if [ "$#" -eq 0 ]; then
    set -- code.py
fi

# Kontrola: je CIRCUITPY pripojeny?
if ! mountpoint -q "$DEST"; then
    echo "[ERR] $DEST neni pripojeny."
    echo "      Zkontroluj, ze je Pico zapojene a v CircuitPython rezimu."
    exit 1
fi

# Kontrola: je RW?
if ! mount | grep -F " $DEST " | grep -q '\brw\b'; then
    echo "[ERR] $DEST je read-only."
    echo "      Reseni:"
    echo "        1) odpoj a znovu zapoj USB"
    echo "        2) safe mode: 2x rychle stiskni RESET na desce"
    echo "        3) zkontroluj boot.py - nesmi tam byt storage.remount(..., readonly=False)"
    exit 1
fi

# Kontrola: existuji vsechny zdrojove soubory?
for src in "$@"; do
    if [ ! -f "$src" ]; then
        echo "[ERR] zdrojovy soubor '$src' neexistuje."
        exit 1
    fi
done

# Kopirovani
for src in "$@"; do
    echo "[..] $src -> $DEST/"
    if ! cp "$src" "$DEST/"; then
        echo "[ERR] kopirovani '$src' selhalo."
        exit 1
    fi
done

# Sync = pockej, az se zapis dostane na flash
echo "[..] sync (cekam na dokonceni zapisu)..."
sync

echo "[OK] hotovo. CircuitPython by se mel sam restartovat."
