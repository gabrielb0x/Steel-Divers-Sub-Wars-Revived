# Pseudo-code source

## `raw/` — sortie brute de Ghidra (générée, non versionnée)

*Avancement estimé : 100 % — toutes les fonctions exportées, rangées par fichier objet d'origine.*

`make export` (ou `ghidra/export.sh`) décompile toutes les fonctions et range chacune dans le fichier objet d'où
elle vient, d'après la table des symboles du linker (`romfs:/map`) :

```
raw/source/main.cpp, raw/source/net/session.cpp, …   code du jeu (chemins d'origine quand ils sont connus)
raw/lib/libnw_gfx/gfx_Model.cpp, …                     NintendoWare, SDK, NEX, Pia, runtime C
raw/unmapped/0x00330000.cpp, …                         fonctions absentes du map, par tranche de 64 Kio
raw/functions.csv                                      adresse, taille (map / Ghidra), nom, objet, fichier
```

Chaque fonction est précédée de son adresse et de sa taille dans le map.

## `scripts/` — scripts Pawn décompilés (générés, non versionnés)

*Avancement estimé : 100 % — les 123 scripts décompilés ; leur lisibilité dépend des noms de `pawn/`.*

`make scripts` désassemble (`scripts/asm/*.asm`) et décompile (`scripts/*.p`) les 123 scripts `romfs:/amx/*.amx`.
Voir [../docs/scripts-pawn.md](../docs/scripts-pawn.md).

## `pawn/` — connaissances sur les scripts (versionné)

*Avancement estimé : 35 % — 343 natives prototypées sur 647 ; 236 noms de fonctions et de globales, environ 1 400 groupes de fonctions restent à nommer.*

- `pawn/natives.inc` : prototypes Pawn des natives (noms de paramètres, `Float:`, références) et énumérations
  (`UID`, `BUTTON`), écrits à partir des implémentations C++ ;
- `pawn/symbols.txt` : noms des fonctions de script sans log et de leurs paramètres, et noms de globales ; un nom
  s'applique à toutes les copies de la fonction dans les autres scripts.

## Améliorer le pseudo-code

*Avancement estimé : 15 % — classes reconstituées : `World`, `Actor`, `AMXLoader`, `NsubShop`… ; la plupart des classes du jeu restent à typer.*

La base Ghidra est jetable (`make analyze` la recrée). Tout ce qu'on comprend va dans deux fichiers versionnés,
réappliqués à chaque export :

- `ghidra/symbols.txt` : nom et prototype C des fonctions (celles absentes du map, ou dont on connaît la signature) ;
- `ghidra/types.h` : structures, énumérations et typedefs reconstitués.

Boucle de travail : lire `raw/`, vérifier dans le désassemblage, compléter `symbols.txt` / `types.h`, `make export`.

Piège connu : `armlink` fusionne les fonctions au code identique. Un appel peut donc porter le nom d'une autre
fonction (par ex. un `printf` de debug vidé qui apparaît comme `Renderer::getActiveMask("source/main.cpp", …)`).

## `src/` — code nettoyé (versionné)

*Avancement estimé : 9 % — 185 fonctions du jeu réécrites sur 2 126 (environ 11 % du code du jeu, hors bibliothèques Nintendo).*

Le C++ réécrit à la main à partir du pseudo-code, avec la même arborescence que `raw/source/` :

| Fichier | Contenu |
|---|---|
| `main.cpp` | démarrage, boucle principale à 30 fps, enchaînement des modes |
| `amx/amxloader.cpp` | chargeurs de scripts : liste, exécution image par image, messages, appels différés, observateurs |
| `game/world.cpp` | monde : pool de 256 acteurs, chargement des niveaux, tampon de replay de 7 s |
| `game/actor.cpp` | cycle de vie d'un acteur : propriétés, script et ses fonctions publiques, mort |
| `sys/system.cpp` | démarrage, tas mémoire, temps, boutons HOME et marche/arrêt |
| `net/connectionInternet.cpp` | jeu en ligne : réseau de la console, connexion au serveur, recherche de partie (critères, attributs, somme de version), session créée ou rejointe, liste de blocage, notifications |

Conventions :

- garder le nom d'origine des classes, méthodes et fichiers (ceux du map et des chaînes `__FILE__`) ;
- indiquer l'adresse d'origine au-dessus de chaque fonction (`// 0x00101118`) ;
- ne pas copier les données du jeu (tables, textes, assets) : les lire depuis le RomFS.
