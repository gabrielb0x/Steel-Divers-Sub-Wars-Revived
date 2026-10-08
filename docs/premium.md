# Version gratuite, premium et contenus additionnels

Sub Wars était un jeu gratuit. La **version complète** (« premium », *enlist* dans le code : s'engager) et cinq
sous-marins historiques se vendaient sur l'eShop sous forme de **contenus additionnels** (DLC). L'eShop ne vend plus
rien depuis 2023 : le mod [`premium`](../mods/premium/mod.toml) débloque tout sans lui. Cette page explique comment
le jeu décide de ce qui est acheté, et ce que le mod change.

## Ce qu'il y a dans le jeu de base

*Avancement estimé : 100 %.*

Tout le contenu premium est déjà dans le RomFS du jeu gratuit : les 7 zones de missions, les 18 sous-marins de base,
les 32 motifs et les 32 membres d'équipage, et même les coques des 5 sous-marins historiques (`n2ply_x001` à
`n2ply_x005`, que les joueurs gratuits voyaient chez les autres en ligne). L'achat n'ajoutait qu'un **droit**, plus,
pour chaque sous-marin historique, une petite archive avec sa **proue** : le modèle détaillé que voit son propre
pilote (`n2ply_x00N_prow`).

| Sous-marin | Fichier | Coque (jeu de base) | Contenu |
|---|---|---|---|
| 19 | `bxml/pscope_ply19` | `n2ply_x002` | 1 |
| 20 | `bxml/pscope_ply20` | `n2ply_x004` | 2 |
| 21 | `bxml/pscope_ply21` | `n2ply_x001` | 3 |
| 22 | `bxml/pscope_ply22` | `n2ply_x003` | 4 |
| 23 | `bxml/pscope_ply23` | `n2ply_x005` | 5 |

Les contenus additionnels forment le titre `0004008C000D7E00` (le jeu est `00040000000D7E00`), chaque achat étant
un « contenu » numéroté de ce titre.

## Comment le jeu vérifie les achats (`source/sys/dlc.cpp`)

*Avancement estimé : 100 %.*

La classe `NsubShop` (un singleton, `getNsubShop()`) enveloppe la bibliothèque d'achat `nn::ec` :

- `updateCondition()` demande à `nn::ec::CTR::DataTitle` la liste des contenus du titre de DLC et, pour chaque
  contenu présent et acheté, met un bit à 1 dans un bitmap de 128 bits (`+0xFA0`, 4 mots) ;
- `checkCondition(n)` lit le bit `n` : vrai si le contenu `n` est acheté ;
- `checkPaidForFullVer()` lit le bit 27 du troisième mot (`+0xFA8`), c'est-à-dire le **contenu 91** : la version
  complète ;
- `mountContentArchive(n)` / `unmountContentArchive()` montent l'archive du contenu `n` sous `content:`
  (`nn::fs::MountAddOnContent`) ;
- le reste (`initializeEc`, `validateSession`, catalogue, `purchaseItem`, `redownloadItem`, solde…) sert la
  boutique et l'écran d'achat, en parlant aux serveurs de l'eShop.

Les scripts y accèdent par les natives `sysDLC*` d'`amxsys` ; `sysDLCCheckPaidForFullVer` et
`sysDLCCheckCondition` sont deux mini-fonctions placées juste avant `checkPaidForFullVer` et `checkCondition`,
dans lesquelles elles « tombent » après avoir chargé le singleton.

**Sous-marins historiques** : leur fichier de propriétés (`bxml/pscope_ply19.bxml`…) contient
`<mount_dlc_arc content_index="n"/>` et un attribut `model_mutable_dlc` au lieu de `model_mutable`.
`Actor::readProperties` monte alors l'archive du contenu si `checkCondition(n)` est vrai, et
`Actor::setAttributeString` ne charge `model_mutable_dlc` que si l'archive est montée (sinon le sous-marin n'a pas
de proue). La coque, `modelship`, vient toujours du jeu de base : c'est elle qu'envoient les autres consoles
(`@syncNetworkSpawn`).

## Ce que la version gratuite limite (scripts Pawn)

*Avancement estimé : 100 %.*

Tous les scripts de modes ont une copie de `isFullVersion()` (`return sysDLCCheckPaidForFullVer();`) :

| Script | Version gratuite | Version complète |
|---|---|---|
| `mode_title` | écran titre au coucher du soleil, mention « Version gratuite » (volet `trial`), bouton « S'engager » | décor de jour, sans la mention ni le bouton |
| `mode_select` | le bouton Boutique propose l'achat (`alert_salemessage02`, puis `mode_sale`) | il ouvre la boutique (`mode_shop`) |
| `mode_mission_select` | seules les deux premières zones | les 7 zones, débloquées par le nombre de médailles |
| `mode_customize` | seuls les sous-marins 1 et 2 (`sub_detail_unlock_not_enlist` sinon) | tous ceux débloqués |
| `mode_lobby` | sous-marins 1 et 2 en ligne (`save.sub.unlock[2..22]` mis à 0) | tous ceux débloqués |

Les sous-marins 19 à 23 suivent `sysDLCCheckCondition(n° − 18)` : au titre, un sous-marin historique choisi mais
plus acheté est remplacé par le n° 1 (`save.sub.typenum`).

## Déblocages et sauvegarde

*Avancement estimé : 100 %.*

En version complète, les sous-marins et les motifs se gagnent par des **récompenses** (`bxml/reward_data` :
`decalNN` pour un motif, `lobby_sub_nameNN` pour un sous-marin, appliquées par `unlockReward`) :

- en solo, aux 3, 4, 8, 9, 15, 18 et 21 médailles d'or (`medal.inc::updateAwardMedal`, `reward100` à `reward106`) :
  les sous-marins 2 et 3 et cinq motifs ;
- **en ligne, à chaque niveau de rang** (`reward02` à `reward42`) : les sous-marins 4 à 18 et la plupart des motifs.
  Sans serveur en ligne, ils étaient devenus impossibles à obtenir.

Les membres d'équipage se trouvent dans les missions (`crew.get`, `saveFoundCrew`). Le tout est gardé dans trois
tableaux de la sauvegarde ([formats.md](formats.md#sauvegarde)) :

- `save.sub.unlock[23]` : sous-marins (l'indice 0 est toujours débloqué) ;
- `save.sub.pattern.unlock[32]` : motifs de coque (*decal*) ;
- `save.sub.crew.unlock[32]` : membres d'équipage.

**Le piège du drapeau premium** : au titre, la première fois que la version complète est présente, le jeu écrit
`save.sub.enlist = 1`. Si plus tard ce drapeau est dans la sauvegarde mais que la version complète a disparu (DLC
effacé), le bouton Start affiche l'erreur **098-0101** (`sysShowErrEULA(98101)`) et la partie ne démarre plus.

## Le mod `premium`

*Avancement estimé : 100 % — vérifié dans Azahar.*

```sh
.venv/bin/python tools/mod.py build premium --install
```

1. `checkPaidForFullVer` et `checkCondition` renvoient toujours vrai (deux patchs de 8 octets) : version complète
   et cinq sous-marins historiques.
2. `updateCondition` (le bitmap ne sert plus) est remplacée par une routine qui met à 1 les trois tableaux de
   déblocage (option `debloquer`, activée par défaut) : les scripts l'appellent au titre, juste après le
   chargement de la sauvegarde, et avant le salon et le hangar. Le jeu enregistre ensuite ces tableaux : les
   déblocages restent même sans le mod, comme s'ils avaient été gagnés.
3. Sans DLC (option `dlc=non`, par défaut), les sous-marins historiques prennent la proue d'un sous-marin du jeu
   de même taille : plus d'archive à monter (`mount_dlc_arc` retiré), `model_mutable_dlc="n2ply_x00N_prow"`
   devient par exemple `model_mutable="n2ply_l001_prow"` (I-400). Une première version leur donnait leur coque
   comme proue : la caméra du pilote se retrouvait dans la coque (toute la vue cachée sur la classe Z de la
   v5200, immense), et les couleurs des motifs ne s'y voyaient pas (le jeu les pose sur le matériau `prow_mat`
   des proues). Avec `dlc=oui`, pour qui a installé dans Azahar le DLC qu'il a acheté, les fichiers d'origine
   restent.
4. Le bouton Boutique du menu recharge le menu : la boutique attendrait l'eShop dans des boucles sans fin.
5. `save.sub.enlist` est écrit dans une globale `mode.sub.enlist`, que la sauvegarde ne garde pas : retirer le mod
   ne déclenche pas l'erreur 098-0101. Une sauvegarde déjà marquée se répare avec `tools/save.py premium-off`.
6. Les motifs débloqués par le mod reçoivent leurs couleurs par défaut (`bxml/sub_color_set`), que le jeu ne
   donne qu'aux motifs débloqués par une récompense : une fois par sauvegarde (`save.sdsw.colors`), au titre, ceux
   dont les trois couleurs sont encore à 0 (`mods/premium/src/colours.p`).

Les missions restent à jouer : elles se débloquent avec les médailles. Pour tout ouvrir d'un coup, l'éditeur de
sauvegarde ([../tools/save.py](../tools/save.py)) sait aussi donner des médailles.

En ligne, ce mod ne compte pas comme de la triche : il donne ce que les joueurs premium avaient.

## Dans la mise à jour v5200

*Avancement estimé : 90 % — vérifié dans Azahar : équipage complet, sous-marins de la mise à jour débloqués ; reste
le détail des « remodelages ».*

La mise à jour ([update-v5200.md](update-v5200.md)) vend davantage :

- **15 sous-marins** à part : les 5 historiques (n° 19 à 23, contenus 1 à 5) et 10 nouveaux (n° 27 à 36 : I-168,
  Type XXI, Blue-Marine, Classe Z, Soryu, USS Nautilus, Classe S, Daphné, Kilo, Victor III ; contenus 6 à 15),
  leur proue dans le contenu additionnel comme celle des historiques (`mount_dlc_arc`). La table des
  correspondances est dans `mode_title` (sous-marins et contenus, 15 cellules chacune).
- **Un « remodelage » de chaque sous-marin** (`save.sub.typeN.expanded`), acheté comme le contenu N + 30.
- **De l'expérience d'équipage** et la version complète (`sysDLCSetFilterModeCrewExp`, `…Enlist`).

`NsubShop::updateCondition` (`0x0013A9B0`) y remplit deux bitmaps : les contenus achetés (`+0x2DB0`, lus par
`checkCondition` et `checkPaidForFullVer`) et les contenus possédés (`+0x2DC0`, lus par la nouvelle native
`sysDLCCheckOwned`, `0x0030B988`). Les sous-marins se débloquent dans `save.sub.unlock[23]` (comme en v0) et dans
`save.sub.unlock2[36]` (n° 1 à 36) et `save.p3.sub.unlock[3]` (n° 37 à 39 : Type ORDI, Fretin, Sous-boss, les
sous-marins de l'ordinateur devenus jouables) ; `updateSubUnlock` (`mode_title`) en déduit `save.sub.owned[36]` et
`save.p3.sub.owned[3]`. L'équipage des sous-marins 37 à 39 est dans `save.p3.sub.crew.unlock[8]`.

Le mod `premium` y fait tout acheter et tout posséder (les trois fonctions de vérification rendent 1), remplit les
huit tableaux de déblocage, donne une proue du jeu aux sous-marins 27 à 36 sans le DLC, et mène au menu le bouton
Boutique et l'invitation à la « boutique d'essai » de la v5200.

**Les couleurs des motifs** : la v5200 resynchronise à chaque démarrage les récompenses avec le niveau en ligne
(`mode_title`, `func_103e4`, nouveau) : tout ce qui est au-dessus du niveau du joueur est reverrouillé, et un motif
reverrouillé reprend des couleurs « par défaut » qui ne sont pas encore lues (0, 0, 0). Le mod redéverrouillait
ensuite tout : les couleurs choisies pour les motifs 6 à 31 (récompenses des niveaux 2 à 42) étaient perdues à
chaque démarrage. Avec `debloquer`, `func_10358` (débloquer ou verrouiller une récompense) ne verrouille plus. `tools/save.py` et le lanceur connaissent les
39 sous-marins et les tableaux de la v5200.

