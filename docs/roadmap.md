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
- [x] Boutique et contenus additionnels (`decomp/src/sys/dlc.cpp`, classe `NsubShop` typée), sauvegarde
      (`decomp/src/sys/savedata.cpp`, globales et natives de sauvegarde dans `decomp/src/amx/amxsys.cpp`)

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

1. ~~**Rétro-ingénierie du client**~~ : PRUDP v1, Kerberos, RMC, structures NEX 3.7, détection de NAT de Pia,
   notifications ([online.md](online.md)).
2. ~~**Serveur autonome**~~ (Python, sans dépendance) : TicketGranting, SecureConnection, NATTraversal, MatchMaking,
   MatchMakingExt, MatchmakeExtension, serveurs « nncs » ; deux royaumes séparés, émulateur et PC ; options
   `max_players` (plus de bots) et `cheats` (tricheurs acceptés, séparés ou refusés).
3. ~~**Validation avec le jeu**~~ : deux Azahar avec le mod `en-ligne` se connectent, se trouvent et jouent une
   bataille ensemble.
4. ~~**Serveur public**~~ : adresse publique trouvée (box, STUN), ports ouverts par UPnP (vérifié avec une
   box), joueurs du réseau du serveur présentés sous l'adresse publique et port de leur jeu redirigé
   ([online.md](online.md#7-joueurs-éloignés--adresses-publiques-et-privées)) ; validé par simulation (deux NAT
   Linux dans des espaces de noms réseau) ; lanceur : arrêt d'un serveur déjà lancé, adresse à partager, test.
5. ~~**Bots pour un joueur seul**~~ : seul `bots_delay` secondes, le joueur joue contre des bots réglés par le
   serveur (équipes 4v4, 1v4…, carte, niveau, durée, noms) ; ils rejoignent le salon comme des joueurs, ont de
   vrais sous-marins, leur nom et leur niveau, et comptent pour la victoire. Vérifié dans Azahar. Le serveur
   règle le jeu par des notifications à lui (variables de script, [online.md](online.md#8-serveur--jeu--les-variables-du-mod)).
   Options du serveur affichées et modifiables dans le lanceur.
6. **À suivre** : des bots qui jouent vraiment comme des joueurs (collisions entre eux, combats entre bots,
   déplacements naturels) ; une vraie partie entre deux maisons ; relais pour les NAT stricts si besoin ;
   migration d'hôte et départs en cours de partie à éprouver.

## Volet 4 — Mods (Azahar, puis portage PC)

Le plan détaillé est dans [mods.md](mods.md) : on publie des recettes (`mods/`), jamais un CIA modifié.

1. ~~**Outillage**~~ : jeu installable dans Azahar (`tools/azahar.py`), mods en recettes construites et installées
   par `tools/mod.py` (textes, BXML, patchs de code IPS) ; reste les scripts Pawn (assembleur AMX).
2. **Scripts Pawn** : ~~patchs ciblés~~ (chaînes et opérandes, réencodage compact identique à l'octet près :
   `tools/amx.py`, recettes `[[amx]]`, mod `triche`) ; ~~assembleur~~ (`tools/amxasm.py` : code, données,
   natives et fonctions publiques ajoutés, crochets sur les instructions existantes, fichiers `.pasm`) ; reste
   du pseudo-Pawn recompilable. Le menu de debug des développeurs en dépend (sa logique et son affichage ont
   été retirés).
3. ~~**Jeu en ligne**~~ : mod `en-ligne` (patch des fonctions *friends* utilisées par `JobCTRLogin`, serveurs de
   détection de NAT redirigés, identité par joueur). Reste : une somme de version propre aux mods de gameplay.
4. **60 fps** : un essai dans Azahar (image intermédiaire interpolée entre deux pas de simulation, commit
   bfac07c) a été abandonné pour l'instant, trop de défauts en jeu ([mods.md](mods.md#60-et-120-images-par-seconde)).
   À reprendre dans le portage PC, où le rendu est à nous : 60, 120 images/s et plus.
5. ~~**Premium**~~ : mod `premium` (version complète et contenus additionnels sans l'eShop, déblocages,
   sous-marins historiques avec leur coque), [premium.md](premium.md).
6. ~~**Sauvegarde**~~ : format décodé, éditeur `tools/save.py`.
7. ~~**Correctifs**~~ : plantage d'Azahar quand une torpille touche un sous-marin sous l'eau (bug de son JIT de
   shaders, contourné dans `shaders/metaball.shbin`), mod `correctifs` inclus partout ([mods.md](mods.md#correctifs)).
8. ~~**Petits mods**~~ : `missions` (toutes les missions), `vitesse` (sous-marin ×2 à ×15), tir sans délai
   (`triche`, option `rafale`).
9. ~~**Pseudo**~~ : en ligne et en local, le nom d'un joueur est le pseudo de sa console (de l'émulateur), plus
   « Citra » pour tout le monde (mod `pseudo`, inclus partout).

## Décisions

- **Version du jeu** : la version de lancement (v0, Europe), celle du dump. Pas de mise à jour disponible (pas de
  3DS pour la dumper) : tout vise cette version.
- **Cibles** : mods pour Azahar d'abord, portage PC ensuite (recompilation statique + HLE). La 3DS n'est pas une
  cible.
- **Licence du dépôt : MIT**. Le code GPL/AGPL (serveur Pretendo, Azahar/Citra) ne peut pas être intégré tel quel : il
  sert de référence, et on écrit nos propres implémentations.
