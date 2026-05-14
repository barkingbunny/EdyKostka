# Zadani pro Program Edy kostku

HW: je zde bezna deska RaspberryPi pico. zakladni verze
Potom pouzivam vlastni HW pro pripojeni periferii. 

Program bude psan v circuitPython

## soupis periferii.

Mame 5 vstupu, kde 4 jsou Off-On spinace, a 1x Off-(ON) (tlacitko)
16 LED vystupu, nejlepe rizene PWM
1x OneWire sbernice
1x vystup pro keep-a-live signal
1x buzzer. 

### LED
|GPIO | Type | off state| group | place | collor| PWM MAX | PWM MIN | 
| ---| --- | --- | --- | --- | ---| --- | 
| 0| Output | LOW | | JERAB | TOP| RED* |
| 1| Output | LOW | | JERAB | TOP| YELLOW* |
| 2| Output | LOW | | SEMAFOR | MID | YELLOW |
| 3| Output | HIGH| | SEMAFOR | TOP | RED |
| 4| Output | HIGH| | SEMAFOR | BOT | GREEN|
| 5| Output | LOW | | POZOR | LEFT | RED |
| 6| Output | LOW | | POZOR | RIGHT | RED |
| 7| Output | HIGH| | BULDOZER | TOP | ORANGE |
| 8| Output | HIGH| | MICHACKA | FRONT | YELLOW | 
| 9| Output | LOW | | JERAB | RIGHT | RED |
|10| Output |LOW | | JERAB | CABIN | RED |
|11| Output |LOW | High| SWITCH | - | YELLOW |
|12| Output |HIGH| | STAVBA | TOP | WHITE|
|13| Output |LOW | | JERAB | LEFT | RED |
|14| Output |LOW | | JERAB | BOT | RED |
|15| Output |LOW | | JERAB | MID | RED |

poznamka: LED s oznacenim * nemohou fungovat zaroven. Muze fungovat jen jedna z techto dvou.

### digital
|GPIO | Type | Function | |NAME|
| ---| --- | --- | ---| 
| 16 | Output | Keep-a-live | | keep-a-live |
| 17 | Bus | OneWire Bus | | OneWireLED |


###SWITCH
numbered from left

|GPIO|Type| color| SWITCH| STYLE | NAME |
| --- | --- | --- | --- | --- | 
|18| Input |YELLOW | 1 | OFF-ON | SWITCH |
|19| Input |YELLOW | 2 | OFF-ON | SWITCH |
|20| Input |GREEN | 4 | OFF-(ON)|SWITCH |
|21| Input |RED |5| OFF-ON| SWITCH |
|22| Input |Grey | 3 | OFF-ON | SWITCH |

### Sound
|GPIO | Type | Function | |
| ---| --- | --- | ---| 
|28| Output | Buzzer | | 

### Pico Internal
|GPIO | Type | Function | |
| ---  --- | --- | ---| 
|24| Input | VBUS sense | Detect USB power or VBUS pin |
|25| Output | System LED | USER LED on board |
|29| Analog Input A3 |  read VSYS/3 through resistor divider and FET Q1 |
|-| A4 Input | Temperature |Read onboard temperature sensor|


## Popis periferii.

### keep-a-live 
* Pripojeno viz tabulka
* keep alive signal - LOW - OFF signal.
Tato periferie udrzuje zapnute napajeni. Je to neco jako watch dog. 
Pozadavek na signal: perioda 10s, Pulz jde do high a trva 400ms, potom signal klesne do LOW a po zbytek periody bude LOW. 

### OneWireLED
* pripojeno viz tabulka
Jedna se o periferii s OneWire LED  Inolux- IN-PI55TATPRPGPB . Je zde 12 kusu teto LED. Je kompaktibilni s protokem WS2812.  

### LED 
* LED - jsou rizene PWM vystupem. 
pripojeno na 
 * pro GPIO 0,1,2,5,6,9,10,11,13,14,15 je stav LOW - LED zhasnuta, 
 * pro GPIO 3,4,7,8,12, je stav High - LED zhasnuta.

LED se budou delit do skupin dle ucelu:
LED:

* STAVBA 
    * 2x RED 
* JERAB
    * 5x RED
    * 1x RED XOR 1x YELLOW
* BAGR
    * 1x ORANGE
* MICHACKA
    * 1x YELLOW
* OSVETLENI
    * 1xWHITE
* SEMAFOR
    * 1x RED
    * 1x YELLOW
    * 1x GREEN
* TLACITKO
    * 1x GREEN


### SWITCH
* Pripojeno viz tabulka SWITCH
* Vstup je default ve stavu - High. Detekovani stavu LOW znaci stisknuti/prepnuti spinace
Vstupy jsou realizovane tlacitky a prepinaci. Je zde potreba mit lehky debouncing a reakce na stisknuti. 
Reakce na stisknuti bude popsana nize. 




# Zadani programu

# Init
pri bootovani chci iniliazicni test. 
potom se prepne program do naslouchani pres seriovou linku

# HW kontext
- **MCU:** Raspberry Pi Pico, vlastní HW pro periferie
- **16 LED** na GPIO 0–15
- **5 vstupů** (spínače/tlačítko) default HIGH, aktivní LOW, s debouncingem
- **1-Wire LED** (Inolux IN-PI55..., 12 ks, WS2812-kompatibilní) 
- **Keep-alive signál** 

## Inicializační test LED po nabootování
Probliknout LED **po skupinách** v daném pořadí, v rámci skupiny **LED po LED** (ne všechny současně):

| Pořadí | Skupina  | GPIO pořadí                  | Logika pořadí                     |
|--------|----------|------------------------------|-----------------------------------|
| 1      | POZOR    | 5, 6                         | LEFT → RIGHT                      |
| 2      | SEMAFOR  | 4, 2, 3                      | BOT → MID → TOP                   |
| 3      | MICHACKA | 8                            | jediná                            |
| 4      | STAVBA   | 12                           | jediná                            |
| 5      | JERAB    | 14, 15, 10, 0, 9, 13, 1      | BOT → MID CABIN → TOP- RIGHT → LEFT → TOP |
| 6      | BULDOZER | 7                            | jediná                            |
| 7      | SWITCH   | 11                           | jediná                            |


Projet postupne LED na 1-wire sbernici. barva bude zelena. postupne od prvni po posledni. 

## REPL režim (po init testu)
Jednoznakové příkazy bez Enteru přes serial:
- `0`–`9`, `a`–`f` — toggle LED na GPIO 0–15 (hex)
- `A` — všechny LED ON
- `Z` — všechny LED OFF
- `S` — výpis svítících LED
- `?` — nápověda
- `W` - zapnout keep a live signal
- `Woff` - vypnout keel a live signal

* pro sekvenci A vem v potaz poznaku pod tabulkou LED. Dva vstupy LED nemohou byt zapnute zaroven, tam to udelej, ze problikava s periodou 1s

## Sledování vstupů
GPIO 18–22 se sledují v hlavní smyčce s debounce ~30 ms, každá změna se tiskne (`STISK` / `uvolneno`).

## keep a live
keep a live signal zatim nebudeme spoustet po zapnuti. pouze na vyzadani obsluhy

## Neimplementováno (zatím)
- PWM řízení LED (zatím jen digitální on/off)
- Reakce na vstupy podle aplikační logiky





