# flash.ps1 - nahraj soubor na pripojenou CIRCUITPY desku (Raspberry Pi Pico).
#
# Pouziti (z PowerShellu v adresari projektu):
#   .\flash.ps1                       # nahraje code.py
#   .\flash.ps1 boot.py               # nahraje jiny soubor
#   .\flash.ps1 code.py lib\foo.py    # vice souboru najednou
#
# Skript najde svazek s labelem CIRCUITPY, zkontroluje, ze je zapisovatelny,
# zkopiruje soubor(y) a flushne write cache (jinak Windows muze drzet zapis
# v cache a deska to nedostane pred reset).
#
# Pokud ti PowerShell hlasi "running scripts is disabled", spust jednou:
#   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned

param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Files
)

$ErrorActionPreference = 'Stop'

if (-not $Files -or $Files.Count -eq 0) {
    $Files = @('code.py')
}

# --- Najit CIRCUITPY drive ---
$volume = $null
try {
    $volume = Get-Volume -ErrorAction Stop |
        Where-Object { $_.FileSystemLabel -eq 'CIRCUITPY' } |
        Select-Object -First 1
} catch {
    Write-Host "[ERR] Get-Volume selhalo: $_"
    exit 1
}

if (-not $volume) {
    Write-Host "[ERR] CIRCUITPY drive nenalezen."
    Write-Host "      Zkontroluj, ze je Pico zapojene a v CircuitPython rezimu."
    Write-Host "      (Pokud vidis RPI-RP2 drive, je deska v bootloader rezimu - nahraj .uf2 misto .py.)"
    exit 1
}

$driveLetter = $volume.DriveLetter
if (-not $driveLetter) {
    Write-Host "[ERR] CIRCUITPY je pripojeny, ale nema priradene pismeno."
    exit 1
}

$dest = "${driveLetter}:\"
Write-Host "[..] CIRCUITPY nalezen na ${driveLetter}:"

# --- Kontrola RW (probni zapis dummy souboru) ---
$testFile = Join-Path $dest ".flash_write_test"
try {
    Set-Content -LiteralPath $testFile -Value 'x' -Encoding ascii -ErrorAction Stop
    Remove-Item -LiteralPath $testFile -Force -ErrorAction Stop
} catch {
    Write-Host "[ERR] ${dest} je read-only ($_)."
    Write-Host "      Reseni:"
    Write-Host "        1) odpoj a znovu zapoj USB"
    Write-Host "        2) safe mode: 2x rychle stiskni RESET na desce"
    Write-Host "        3) zkontroluj boot.py - nesmi tam byt storage.remount(..., readonly=False)"
    exit 1
}

# --- Kontrola: existuji vsechny zdrojove soubory? ---
foreach ($src in $Files) {
    if (-not (Test-Path -LiteralPath $src -PathType Leaf)) {
        Write-Host "[ERR] zdrojovy soubor '$src' neexistuje."
        exit 1
    }
}

# --- Kopirovani ---
foreach ($src in $Files) {
    Write-Host "[..] $src -> $dest"
    try {
        Copy-Item -LiteralPath $src -Destination $dest -Force -ErrorAction Stop
    } catch {
        Write-Host "[ERR] kopirovani '$src' selhalo: $_"
        exit 1
    }
}

# --- Sync = flush write cache pro CIRCUITPY drive ---
Write-Host "[..] flush write cache..."
try {
    Write-VolumeCache -DriveLetter $driveLetter -ErrorAction Stop
} catch {
    Write-Host "[!]  Write-VolumeCache nedostupne ($_) - cekam 2 s misto toho."
    Start-Sleep -Seconds 2
}

Write-Host "[OK] hotovo. CircuitPython by se mel sam restartovat."
