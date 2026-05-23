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

### LED-Table
|GPIO | Type | off state| group | place | collor| PWM MAX | PWM MIN | 
| ---| --- | --- | --- | --- | ---| --- | 
| 0| Output | LOW | | JERAB | TOP| RED* | 8 % | 
| 1| Output | LOW | | JERAB | TOP| YELLOW* | 20 % | 
| 2| Output | LOW | | SEMAFOR | MID | YELLOW | 100 % |
| 3| Output | HIGH| | SEMAFOR | TOP | RED | 100 % |
| 4| Output | HIGH| | SEMAFOR | BOT | GREEN| 100 % |
| 5| Output | LOW | | POZOR | LEFT | RED | 100 % |
| 6| Output | LOW | | POZOR | RIGHT | RED | 100 % |
| 7| Output | HIGH| | BULDOZER | TOP | ORANGE | 50% | 
| 8| Output | HIGH| | MICHACKA | FRONT | YELLOW | 100 % | 
| 9| Output | LOW | | JERAB | RIGHT | RED | 100 % |
|10| Output |LOW | | JERAB | CABIN | RED | 100 % |
|11| Output |LOW | High| SWITCH | - | YELLOW | 100 % |
|12| Output |HIGH| | STAVBA | TOP | WHITE| 40 % |
|13| Output |LOW | | JERAB | LEFT | RED | 100 % |
|14| Output |LOW | | JERAB | BOT | RED | 100 % |
|15| Output |LOW | | JERAB | MID | RED | 100 % |
|-| OneWire|-|-| AUTO | - | RGB | 8% |

poznamka: LED s oznacenim * nemohou fungovat zaroven. Muze fungovat jen jedna z techto dvou.

### digital
|GPIO | Type | Function | |NAME|
| ---| --- | --- | ---| 
| 16 | Output | Keep-a-live | | keep-a-live |
| 17 | Bus | OneWire Bus | | OneWireLED |


### SWITCH
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
* LED - jsou rizene PWM vystupem s frekvenci 500Hz.
pripojeno na 
 * pro GPIO 0,1,2,5,6,9,10,11,13,14,15 je stav LOW - LED zhasnuta, 
 * pro GPIO 3,4,7,8,12, je stav High - LED zhasnuta.

LED se deli do skupin dle ucelu:

* POZOR
    * 2x RED (LEFT, RIGHT)
* JERAB
    * 5x RED
    * 1x RED XOR 1x YELLOW
* BAGR
    * 1x ORANGE
* MICHACKA
    * 1x YELLOW
* STAVBA
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

## Init
pri bootovani chci iniliazicni test. 
potom se prepne program do naslouchani pres seriovou linku

## HW kontext
- **MCU:** Raspberry Pi Pico, vlastní HW pro periferie
- **16 LED** na GPIO 0–15
- **5 vstupů** (spínače/tlačítko) default HIGH, aktivní LOW, s debouncingem
- **1-Wire LED** (Inolux IN-PI55..., 12 ks, WS2812-kompatibilní) 
- **Keep-alive signál** 

## System

na pozadi bezi keep-a-live signal. Neni potreba ho kontrolovat. 

### funkce *sleepBox*
Šetřící režim aktivuje se po `SLEEP_BOX_TIMEOUT_S` nečinnosti vstupů.

**Co se počítá jako vstup:** pouze fyzické spínače na GPIO 18-22.
Serial REPL se do nečinnosti **nezapočítává** (testovací nástroj).

**Po aktivaci sleepBox:**
* všechny LED výstupy se vypnou (PWM LED 0-15 + OneWire pásek)
* všechny běžící HRA funkce se zastaví
  (MajakBuldozer, RozsvitJerab, RozsvitStavbu, PustAuto, vabeniKoristi, PozorStavba)
* keep-a-live signál **běží dál** (systémová funkce — vypne ho až *ShutDown*)

**Při zaznamenání změny vstupu** (libovolný spínač 18-22) se *sleepBox*
deaktivuje, časovač se vynuluje, HRA se vrátí do **defaultního stavu**:
PozorStavba začne znovu blikat a *vabeniKoristi* se naplánuje na obvyklé
zpoždění `VABENI_BOOT_DELAY_S` po probuzení.

### funkce *ShutDown*
Trvalé vypnutí systému.

Časovač startuje **v okamžiku aktivace sleepBox** a běží `SHUTDOWN_TIMEOUT_S`.
Pokud se za tuto dobu nikdo nedotkne vstupů (a tím neukončí sleepBox),
*ShutDown* deaktivuje signál keep-a-live, čímž externí HW odřízne napájení.

**Po ShutDown už systém neběží** — nic se neaktivuje, nic neblika.
Procesor může být uveden do hlubokého spánku (deep sleep), je-li to možné.
Probuzení/návrat do běhu je možný **pouze přes nový boot** (cyklus napájení,
USB reset). Žádná softwarová cesta zpět neexistuje.


## Inicializační test LED po nabootování
Probliknout LED **po skupinách** v daném pořadí, v rámci skupiny
**LED po LED** (ne všechny současně). Každá LED svítí po dobu
`LED_TEST_ON_S` sekund (default 0.1 s), pak zhasne a hned se rozsvítí další.
Konstanta `LED_TEST_ON_S` je definovaná v `code.py` a lze ji ladit
pro rychlejší/pomalejší test. 


| Pořadí | Skupina  | GPIO pořadí                  | Logika pořadí                     |
|--------|----------|------------------------------|-----------------------------------|
| 1      | POZOR    | 5, 6                         | LEFT → RIGHT                      |
| 2      | SEMAFOR  | 4, 2, 3                      | BOT → MID → TOP                   |
| 3      | MICHACKA | 8                            | jediná                            |
| 4      | STAVBA   | 12                           | jediná                            |
| 5      | JERAB    | 14, 15, 10, 0, 9, 13, 1      | BOT → MID → CABIN → TOP-RED → RIGHT → LEFT → TOP-YELLOW |
| 6      | BULDOZER | 7                            | jediná                            |
| 7      | TLACITKO | 11                           | jediná                            |
| 8      | ONEWIRE  | one wire protoklol           | 12 kusu led, postupne rozsvitit / zhasnout| 


Projet postupne LED na 1-wire sbernici. barva bude zelena, intenzita 0.1, postupne od prvni po posledni. vzdy se led rozsviti a zhasne. Po te se rozsviti druhe led. 

## REPL režim (po init testu)
Příkazy přes serial, potvrzované **Enterem** (CR/LF, případně mezera/tab).
Znaky se při psaní viditelně echují zpět, Backspace maže poslední znak.

| Příkaz           | Akce                                                                 |
| ---------------- | -------------------------------------------------------------------- |
| `0`–`9`, `a`–`f` | toggle LED na GPIO 0–15 (hex)                                        |
| `A`              | všechny LED ON                                                       |
| `Z`              | všechny LED OFF                                                      |
| `S`              | výpis svítících LED                                                  |
| `W`              | zapnout keep-a-live signál                                           |
| `Woff`           | vypnout keep-a-live signál                                           |
| `N`              | opakovat 1-wire LED test (R/G/B smoke + sekvence)                    |
| `B`              | toggle MajakBuldozer                                                 |
| `X`              | obnovit PozorStavba (po manuálním toggle LED 5/6)                    |
| `D`              | výpis aktuální duty (zda je všude stejná)                            |
| `D<n>`           | nastavit PWM duty 0–100 % pro **všechny** LED (každá clamped na své PWM_MAX) |
| `P`              | výpis duty + PWM_MAX všech LED                                       |
| `P<hex>=<n>`     | nastavit PWM duty pro **jednu** LED a zapnout ji (např. `Pa=30` → LED 10 na 30 %); clamped na PWM_MAX_PCT[n] |
| `+` / `-`        | ±5 % krok duty na poslední LED z příkazu `P<hex>=<n>`                |
| `F`              | výpis aktuální PWM frekvence                                         |
| `F<n>`           | nastavit PWM frekvenci v Hz (sdílená všemi LED, např. `F1000`)       |
| `FactoryRESET`   | nastavit default hodnoty                                             |
| `?`              | nápověda                                                             |

* pro sekvenci A vem v potaz poznamku pod tabulkou LED. Dva vystupy LED nemohou byt zapnute zaroven, tam to udelej, ze problikava s periodou 1s
* manuální toggle LED ve skupině POZOR (`5` nebo `6`) pauzuje funkci *PozorStavba* — obnovení příkazem `X`
* po nastavení intenzity přes `P<hex>=<n>` se daná LED automaticky zapne

## Sledování vstupů
GPIO 18–22 se sledují v hlavní smyčce s debounce ~30 ms, každá změna se tiskne (`STISK` / `uvolneno`).

## PWM rizerni LED. 
PWM pro kazdou LED bude mozne mit individualni. Frekvence bude totozna pro vsechny LED, lae bude nastavitelna pomoci prikazu. 

PWM default value jsou definovany v tebulce LED jako PWM MAX. Tyto hodnoty budou ulozene jako konstanty a budou v pripade prikazu `FactoryRESET` v REPL rezimu nahrany misto aktualnich.

PWM hodnoty pro kazdou LED se budou ukladat do lokalni pameti, aby se daly vyvolat po resetu procesoru. Nastavovat se budou v REPL rezimu.  

- PWM řízení LED bude udelano pro kazdou led. Nastaveni bude mozno udelat pro kazdou LED zvlast, aby se dala odladit jeji intenzita. Pri zadavani pres CMD prosim viditelne vypisovat znaky, abych videl co pisi. Po nastaveni intenzity u LED automaticky ji zapnout. 



# Samotny program - HRA

## SWITCH
table 

| SWITCH| ACTION | NAME |
| --- | --- | --- |  
| 1 | MajakBuldozer |
| 2 | RozsvitJerab |
| 3 | RozsvitStavbu |
| 4 | PustAuto |
| 5 |  --rozsviti vsechny LED, ktere jsou k dispozici.-- |

pri sepnuti daneho tlacitka se spusti akce. Reaguje se na nabeznou hranu. Pokud se tlacitko vypne, tak se deaktivuje i dana funkce a vrati vse zpet jak bylo predtim. Jedinou vyjimkou je tlacitko 4, ktere je pouze na stisk. Tam funkce dobehne dokonce. 

Tlacitka a funkce jsou na sobe nezavisle, muze bezet soucasne vice funkci. 

## Svetlo tlacitko 
*vabeniKoristi* funkce - svetlo pro *TLACITKO*  se spusti asi 5s po nabehnuti do programu HRA. LED lehce vabi, aby si ho nekdo vsiml. Jeho intenzita je zmensena na 50 % z PWM_MAX dané LED a postupne pulzuje, aby privabyl k sobe pozornost. Pulzuje jako klidne buseni srdce. 

## Pozor Stavba
*PozorStavba* funkce bezi automaticky po nabootovani systemu. Funkce blika dvemi LED ve stylu Pozor semaforu, ktery dava najevo nebezpeci. Tedy blika cervenymi led ve skupine POZOR

## Buldozer
Funkce *MajakBuldozer* bude pulzovat pomoci zmeny Duty v PWM vystupu. Melo by to pusobit jako blikajici majak auta na stavbe. Tedy pomalejsi pulzovani z 0% na MAX, kde to na MAX bude nejkratsi dobu a potom to pujde zase do 0%. 

## STAVBA
*RozsvitStavbu* funkce udela, ze rozsviti LED STABA a zaroven rozsviti LED MICHACKA. LED STAVBA se bude rozsvicet postupne. Aby se to lidkemu oku zdalo byt jako postupne nabihani sodikove vybojky.

## JERAB
*RozsvitJerab* funkce rozsviti Jerab. Led se postupne zapnou, stejnou sekvenci jaka je v Init, s vynechanim Zlute LED. Prodleva je `JERAB_INIT_DELAY_MS` mezi LED. 
Zluta LED se nerozsviti hned, zacne problikavat az asi po 4s po zapnuti posledni LED. LED bude problikavat s casovanim dle popisu nize. 

* casovani LED TOP,- 300ms YELLOW, 3s RED.

## SEMAFOR
*PustAuto* funkce 
CASOVANI:
| Prechod fazi | prodleva mezi fazemi |
| --- | --- | 
| INIT -> RUN_SEMAFOR |  3s |
| RUN_SEMFOR -> GO  | 1s|
| GO -> ODJETO | 3s | 
| ODJETO -> END | 3s|

* samotne trvani dane faze se lisi, zavisi na narocnosti kroku provadenych v dane fazi. 

pri zapnuti SEMAFOR se funkce vabeniKoristi deaktivuje. 

### faze Init
sviti cervena LED na Semaforu, Sviti 1.OneWire LED z retezu One Wire Bilou barvou a sviti stale , dokud se nestane neco dle navodu.
### RUN_SEMAFOR
Klasickym zpusobem probehnou barvy na semaforu s typickym casovanim a zustane svitit zelena
### GO
One wire LED se budou postupne rozsvecet v bile barve, aby zpusobily efekt jedouci cary, ktera zrychluje. Tedy prvni led sviti a postupne pres zhasinani prechazi do druhe PWM, ktera se zase roszveci. Takto se projde cely pas. Az dojde na posledni LED, ktera bude sviti nejkratsi dobu a potom zhasne. 
### ODJETO
Dale sviti zelena. Ta se zase opet klasickym zpusobem semaforu prehodi na cervenou barvu. Tedy Zelena sviti -> Prejde na zlutou -> prejde na cervenou. 
### END
vsechny LED v tomto cyklu zhasnou a zapne se funkce *vabeniKoristi* s prodlenim asi 4s


# Tabulka s konstantami

Všechny laditelné časové konstanty programu. Default hodnoty
jsou definovány v `code.py` na začátku souboru.

| konstanta              | default | jednotka | popis                                       |
| ---------------------- | ------- | -------- | ------------------------------------------- |
| `LED_TEST_ON_S`        | 0.15    | s        | doba svícení jedné LED v init testu         |
| `SLEEP_BOX_TIMEOUT_S`  | 600     | s        | nečinnost vstupů → přechod do sleepBox      |
| `SHUTDOWN_TIMEOUT_S`   | 600     | s        | doba v sleepBox → vypnutí keep-a-live       |
| `JERAB_INIT_DELAY_MS`  | 100     | ms       | Delay pri zapinani LED u Jerabu pri zapnuti|



# DEBUG

tato sekce se nakonec odebre, slouzi pouze pro debug.

pomoci LED na desce zobrazuj keep-a-live signal. sepnuty rozsvit, rozepnuty - zhasni. Prodlouzi puls rozsviceni alespon na 1s.




