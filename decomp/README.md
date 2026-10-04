# Pseudo-code source

## `raw/` — sortie brute de Ghidra (générée, non versionnée)

`make export` (ou `ghidra/export.sh`) décompile toutes les fonctions et range chacune dans le fichier objet d'où
elle vient, d'après la table des symboles du linker (`romfs:/map`) :

```
raw/source/main.cpp, raw/source/net/session.cpp, …   code du jeu (chemins d'origine quand ils sont connus)
raw/lib/libnw_gfx/gfx_Model.cpp, …                     NintendoWare, SDK, NEX, Pia, runtime C
raw/unmapped/0x00330000.cpp, …                         fonctions absentes du map, par tranche de 64 Kio
raw/functions.csv                                      adresse, taille (map / Ghidra), nom, objet, fichier
```

Chaque fonction est précédée de son adresse et de sa taille dans le map.

## Améliorer le pseudo-code

La base Ghidra est jetable (`make analyze` la recrée). Tout ce qu'on comprend va dans deux fichiers versionnés,
réappliqués à chaque export :

- `ghidra/symbols.txt` : nom et prototype C des fonctions (celles absentes du map, ou dont on connaît la signature) ;
- `ghidra/types.h` : structures, énumérations et typedefs reconstitués.

Boucle de travail : lire `raw/`, vérifier dans le désassemblage, compléter `symbols.txt` / `types.h`, `make export`.

Piège connu : `armlink` fusionne les fonctions au code identique. Un appel peut donc porter le nom d'une autre
fonction (par ex. un `printf` de debug vidé qui apparaît comme `Renderer::getActiveMask("source/main.cpp", …)`).

## `src/` — code nettoyé (versionné)

Le C++ réécrit à la main à partir du pseudo-code, avec la même arborescence que `raw/source/`. Conventions :

- garder le nom d'origine des classes, méthodes et fichiers (ceux du map et des chaînes `__FILE__`) ;
- indiquer l'adresse d'origine au-dessus de chaque fonction (`// 0x00101118`) ;
- ne pas copier les données du jeu (tables, textes, assets) : les lire depuis le RomFS.
