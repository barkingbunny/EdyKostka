# Zadani pro Program Edy kostku

HW: je zde bezna deska RaspberryPi pico. zakladni verze
Potom pouzivam vlastni HW pro pripojeni periferii. 

Program bude psan v circuitPython



## soupis periferii.

Mame 5 vstupu, kde 4 jsou Off-On spinace, a 1x Off-(ON) (tlacitko)
16 LED vystupu, nejlepe rizene PWM
1x OneWire sbernice
1x vystup pro keep-a-live signal

## Popis periferii.

### keep-a-live 
* Pripojeno na GPIO 16
* keep alive signal - LOW - OFF signal.
 Tato periferie udrzuje zapnute napajeni. Je to neco jako watch dog. 
Pozadavek na signal: perioda 10s, Pulz jde do high a trva 400ms, potom signal klesne do LOW a po zbytek periody bude LOW. 

### One wire periferie
* pripojeno na GPIO17
Jedna se o periferii s OneWire LED  Inolux- IN-PI55TATPRPGPB . Je zde 12 kusu teto LED. 

### Vstupy
* Pripojeno na GPIO18 - GPIO22 
* Vstup je default ve stavu - High. Detekovani stavu LOW znaci stisknuti/prepnuti spinace
Vstupy jsou realizovane tlacitky a prepinaci. Je zde potreba mit lehky debouncing a reakce na stisknuti. 
Reakce na stisknuti bude popsana nize. 

### LED 
* LED - jsou rizene PWM vystupem. 
pripojeno na 
 * pro GPIO 0,1,2,5,6,9,10,13,14,15 je stav LOW - LED zhasnuta, 
 * pro GPIO 3,4,7,8,11,12, je stav High - LED zhasnuta.

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


LED

|GPIO | off state| on state| group | place | collor|
| ---| --- | --- | --- | --- | ---| 
|0| | | JERAB | TOP| RED |
|1| | | JERAB | TOP| YELLOW |
|2| | | SEMAFOR | MID | ORANGE |
|3| | | SEMAFOR | TOP | RED |
|4| | | SEMAFOR | BOT | GREEN|
|5| | | POZOR | LEFT | RED |
|6| | | POZOR | RIGHT | RED |
|7| | | BULDOZER | TOP | ORANGE |
|8| | | MICHACKA | FRONT | YELLOW | 
|9| | | JERAB | RIGHT | RED |
|10| | | JERAB | CABIN | RED |
|11| LOW | High| SWITCH | - | YELLOW |
|12| | | STAVBA | TOP | WHITE|
|13| | | JERAB | LEFT | RED |
|14| | | JERAB | BOT | RED |
|15| | | JERAB | MID | RED |


SWITCH
numbered from left

|GPIO| color| SWITCH| STYLE |
| --- | --- | --- | --- | 
|18| YELLOW | 1 | OFF-ON |
|19| YELLOW | 2 | OFF-ON |
|20| GREEN | 4 | OFF-(ON)|
|21| RED |5| OFF-ON|




