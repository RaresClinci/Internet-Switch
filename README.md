
## Cerinta 1: Procesul de comutare
 La aceasta cerinta, am declarat un mac table ca dictionar si am implementat logica de transmitere

## Cerinta 2: VLAN
 Prima parte a rezolvari a presupus parsarea fisierelor config, rezultand
dictionarul vlan cu corespondenta nume port - vlan si prioritatea pe care o vom folosi la cerinta 3.
 A doua parte a reprezentat un wrapper in jurul functiei de trimitere
care face urmatoarele:
    - filtreaza pachetele venite de pe porturi trunk fara header vlan
    - filtreaza pachetele care trebuiau trimise pe acces port, dar nu sunt in vlanul corect
    - adauga header vlan la pachetele venite de la acces ports
    - elimina header vlan inainte sa trimita pachete pe acces port

## Cerinta 3: STP
 Prima oara am creat functionalitatea pentru threadul care trimite
pachete in fiecare secunda, unde am urmarit pseudocodul de pe ocw. Am
creat pachetele conform documentatiei oferite, umpland campurile
neutilizate cu 0.
 Pentru threadul principal, am impartit prelucrarea pachetelor in 2
cazuri: normale si bdpu. Cele bdpu sunt redirectate spre o functie unde
sunt extrase datele root_bridge, cost si bridge_id, apoi se aplica
algoritmul prezentat pe ocw.
 In final, pentru a aplica STP in directarea pachetelor, inainte de
a se adauga porturi in mac_table sau a se trimite pachete, se verifica
daca portul respectiv nu este blocat.
