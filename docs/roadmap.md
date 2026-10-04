# Feuille de route

## Volet 1 — Pseudo-code source (`decomp/`)

But : un code C++ lisible qui montre comment le jeu était écrit.

Fait :
- [x] Extraction du CIA, conversion `code.bin` → ELF (`tools/`)
- [x] Projet Ghidra : 9431 fonctions nommées depuis `romfs:/map`, 439 fonctions retrouvées via les tables de pointeurs,
      wrappers SVC annotés (`ghidra/scripts/`)
- [x] Export du pseudo-code brut, un fichier par fichier objet d'origine (`decomp/raw/`, généré localement)
- [x] Connaissances versionnées (`ghidra/symbols.txt`, `ghidra/types.h`) réappliquées à chaque export ; premières
      entrées : runtime C (`memcpy`, `strlen`, `__aeabi_uidiv`…), `operator new`, prototypes de la séquence de démarrage
- [x] Premier fichier nettoyé : `decomp/src/main.cpp` (démarrage, système de « modes », boucle à 30 fps, rendu stéréo)
- [x] Scripts Pawn : désassembleur + décompilateur (`tools/amx.py`, `tools/amxdec.py`), 123 scripts en pseudo-Pawn ;
      647 natives retrouvées et typées dans Ghidra, types de paramètres déduits du C++ (`tools/native_types.py`)
- [x] Classes `World` et `AMXLoader` (vtable) typées ; faux « no-return » de Ghidra corrigés (378 → 41)

À faire :
1. **Types** : reconstituer les classes du jeu (`Actor`, `World`, `Session`, `Connection`, `Model`…) dans Ghidra à
   partir des constructeurs et des vtables, puis réexporter : le pseudo-code devient beaucoup plus lisible.
2. **Nettoyage** module par module dans `decomp/src/`, avec la même arborescence que `source/`, en commençant par
   `main.cpp`, `sys/system.cpp`, `game/world.cpp`, `game/actor.cpp` et `amx/*` (les natives appelées par les scripts).
3. **Scripts Pawn** : prototypes des natives écrits (`decomp/pawn/natives.inc`), noms propagés entre scripts,
   états Pawn décompilés ; continuer à nommer les ~1 400 groupes de fonctions restants et les globales
   (`decomp/pawn/symbols.txt`).
4. ~~**Formats maison**~~ : BXML dans les deux sens (`tools/bxml.py`, XML lisible, réécriture identique à l'octet
   près pour les 490 fichiers) ; `hmap` et `edge` entièrement documentés ([formats.md](formats.md)).

## Volet 2 — Portage PC (`port/`)

Approche recommandée : **recompilation statique + HLE, puis remplacement progressif par le code décompilé**
(la méthode de Zelda64Recomp ou Unleashed Recompiled).

- Le jeu tourne sur PC bien avant la fin de la décompilation.
- Les bibliothèques Nintendo (NEX, Pia, NintendoWare, SDK : 80 % du code) tournent telles quelles, sans réécriture.
- La pile réseau d'origine fonctionne sur des sockets PC, donc reste compatible avec les serveurs NEX.
- Chaque fonction décompilée du volet 1 peut remplacer sa version recompilée : c'est là que se feront les
  améliorations (écran large, haute résolution, 60 fps).

Étapes :
1. **Recompilateur ARM11 → C** (`tools/recomp/`) : ARMv6K + VFPv2, liste des fonctions issue du map et de Ghidra,
   tables de `switch`, appels indirects (vtables) via une table adresse → fonction.
2. **Runtime** (`port/runtime/`) : espace mémoire 3DS, threads et synchronisation (SVC), HLE des services utilisés :
   `fs` → RomFS + sauvegardes, `hid`/`ir` → clavier/manette, `apt`, `cfg`, `ptm`, `ac`, `frd`…
3. **Rendu** : commandes PICA200 (via `gsp::Gpu` / `libgles2`) → OpenGL ou Vulkan, deux écrans, montée en résolution.
4. **Audio** : HLE du DSP (voix, ADPCM, mixage) → SDL.
5. **Réseau** : `soc:U`/`ssl:C`/`http:C` → sockets PC ; `frd:u` (authentification NASC) → serveur configurable.

Alternative : portage « source pur » (tout décompiler en C++ compilable, réécrire les couches `nn`/`nw`). Plus propre
au final, mais rien ne tourne avant que tout soit terminé.

## Volet 3 — Serveur online (`server/`)

Constat : le serveur ne gère que l'authentification, le matchmaking et le NAT traversal ; les parties elles-mêmes
se jouent en P2P via Pia. Aucune bibliothèque NEX de classement ou de stockage n'est liée au jeu.

1. **Référence** : le serveur de [Pretendo](https://github.com/PretendoNetwork/steel-diver-sub-wars) (Go, AGPL-3.0)
   fonctionne déjà avec les vraies 3DS, mais dépend de leur infrastructure de comptes.
2. **Serveur autonome** : PRUDP + RMC (NEX 3.7), protocoles TicketGranting, SecureConnection, NATTraversal,
   MatchMaking, MatchMakingExt et MatchmakeExtension, sans dépendance externe, plus un NASC minimal pour les 3DS.
3. **Validation** : fait pour la v0 ([online.md](online.md)) : méthodes RMC appelées, session `Steel Matcher`
   (1 à 8 joueurs, mode 1000), attributs (continent, type de salon, niveau, somme de version).
4. **NAT** : Pia fait déjà du NAT traversal ; prévoir un relais pour les NAT stricts si besoin.

## Volet 4 — Mods (sur 3DS et émulateur)

Le plan détaillé est dans [mods.md](mods.md) : on publie des patchs (dossier Luma3DS / Azahar), jamais un CIA modifié.

1. **Outillage** : données (fait : `tools/bxml.py`) ; scripts Pawn (assembleur AMX ou pseudo-Pawn recompilable) ;
   construction du dossier de mod et d'un patch IPS/BPS du code.
2. **Jeu en ligne** : patch de `JobCTRLogin` pour viser notre serveur (volet 3), somme de version propre au mod.
3. **Menu de debug** des développeurs, encore présent dans les scripts : le réactiver.
4. **60 fps** : affichage interpolé entre deux pas de simulation, d'abord dans le portage PC.

## Décisions à prendre

- **Version du jeu** : le dump est la v0 de lancement. Le jeu a reçu des mises à jour (1.1 en mars 2014,
  2.0 en juin 2014). Il faut dumper la dernière mise à jour (`0004000E000D7E00`) et la mettre dans `cia/` avant de
  commencer le portage et le serveur. Elle remplace tout le CXI ; il faudra vérifier que `romfs:/map` y est toujours.
- **Licence du dépôt : MIT** (choisie). Le code GPL/AGPL (serveur Pretendo, composants d'Azahar/Citra) ne peut
  donc pas être intégré tel quel : il sert de référence, et on écrit nos propres implémentations.
