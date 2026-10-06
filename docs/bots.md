# Des bots qui jouent comme des joueurs

En ligne, les sous-marins pilotés par l'ordinateur ne sont plus les bots du jeu. Il s'agit des bots du serveur
pour un joueur seul et de ceux que le jeu ajoute pour compléter les équipes. Le mod
[`en-ligne`](../mods/en-ligne/mod.toml) leur donne un pilote écrit en Pawn
([`mods/en-ligne/src/bots_ia.p`](../mods/en-ligne/src/bots_ia.p)), compilé par `tools/pawn2pasm.py` et essayé dans
un bac à sable (`tools/botsim.py`). Hors ligne (missions), le jeu garde ses propres bots.

## Ce qui n'allait pas avec les bots du jeu

*Avancement estimé : 100 % — tout vient de la lecture des scripts (`decomp/scripts/surface_sub.p`,
`surface_torpedo.p`, `surface_torpedo_p_homing.p`).*

- **Ils traversent les murs et les sous-marins.** `surface_sub` écrit sa position à chaque image
  (`actorSetPosition`) et n'a pas de `@eventCollide` : le moteur lui signale bien les contacts
  (`Actor::procCollisions`), mais personne ne les lit. Le joueur, lui, se repousse dans son `@eventCollide`
  (`pscope_player.p`).
- **Ils tournent en rond autour de leur cible.** Leur cap suit la cible à 0,01 radian par image au plus. Comme ils
  ne reculent jamais, ils décrivent un cercle de près de 300 unités de rayon autour d'un joueur proche.
- **Ils ne se battent pas entre eux.** Ils ne cherchent que les sous-marins de l'autre équipe. Surtout, leurs
  torpilles (`enemy`) ignorent les autres bots : `surface_torpedo.p @eventCollide` compare le sous-marin touché
  avec son propre `npcActorId`, c'est-à-dire avec lui-même. En ligne, leurs torpilles à tête chercheuse ne
  touchent rien du tout : leur `@eventCollide` ne les traite qu'hors ligne.
- **Ils ne touchent que le joueur de leur console.** Leurs torpilles appellent `UID_PLAYER`, le joueur local, qui
  vérifie que le coup est pour lui. Les joueurs des autres consoles ne sont donc jamais touchés. Ils infligent 10
  points de dégâts, quelle que soit l'équipe.
- **Ils tirent sans viser.** Ils tirent droit devant tous les 250 images après avoir « visé » la cible, sans
  tenir compte de leur cap ni du mouvement de la cible. Ils ne reculent pas, n'esquivent pas, et n'utilisent ni
  le masqueur ni les torpilles à tête chercheuse.

## Le pilote

*Avancement estimé : 90 % — essayé dans le bac à sable ; reste à le voir dans Azahar.*

- **La physique d'un joueur** (`pscope_player.p func_12184`) : poussée et traînée (0,038), taux de virage qui suit
  le manche avec de l'inertie, vitesse de plongée. Ce sont les caractéristiques de son sous-marin
  (`bxml/pscope_plyNN_stats` et les tables `table_maxturn`, `table_below_accel`, `table_dive_rate`) : virage,
  accélération, plongée, niveau et nombre de torpilles, rechargement, cadence, air du masqueur. Un bot du serveur
  a celles du sous-marin qu'il montre (`server.bots.sub<k>`), un bot du jeu celles du premier.
- **Les collisions** : un `@eventCollide` ajouté à `surface_sub` le repousse de la carte et des autres
  sous-marins, et retire la vitesse qui l'y enfoncerait. Il regarde aussi devant lui (`worldClipLine`, sept caps)
  pour contourner un obstacle, toujours par le même côté tant que le passage est bouché. Il sonde le fond, et
  recule s'il n'a presque pas bougé pendant deux secondes.
- **Les cibles** : tout sous-marin ennemi, joueur ou bot, de cette console ou d'une autre (`worldFindActors`,
  types `0x40000` et `0x80000`). Il préfère le plus proche, le plus abîmé, celui qu'il voit. Un ennemi masqué
  disparaît au-delà de 1 200 unités : il va voir là où il l'a perdu. Sans cible en vue, il va vers la bataille.
- **La visée** : il vise là où la cible sera quand la torpille y arrivera. Il connaît la course exacte d'une
  torpille partie de l'arrêt, 118,8 × (n − 100 × (1 − 0,99ⁿ)) unités en n images (`func_1778`, `func_2ef4`).
  Il suppose que la cible garde sa vitesse et son taux de virage (un virage régulier est un cercle). Il trouve le
  temps de rencontre par dichotomie et tire en trois dimensions : la torpille part inclinée vers la profondeur de
  la cible. Il ne tire que si la ligne est dégagée, sans coéquipier à moins de 220 unités de la trajectoire, et
  avec son cap à moins de 5°. Une cible qui change de sens de virage n'est visée que de près.
- **Le combat** : il garde ses distances (2 200 à 3 000 unités, 1 700 contre une cible agile), recule face à un
  ennemi trop proche et ne l'éperonne jamais. Il se met à la profondeur de sa cible. Une torpille qui va passer
  près de lui, il la voit venir : il s'écarte de sa trajectoire et change de profondeur, parce qu'une torpille
  garde sa profondeur.
- **Torpilles à tête chercheuse** : une ou deux par vie, celles des joueurs (`surface_torpedo_p_homing`,
  verrouillées par `@lockOnTarget`). Il les tire sur une cible qui vire fort ou passe vite, ou quand il est
  abîmé.
- **Coque basse** (moins de 40 %) : il garde sa cible, recule en tirant, et quand un ennemi approche il passe sous
  son masqueur (`masker`, `masker_on`, comme un joueur : 300 images pour 33,3 d'air) et s'enfuit en profondeur.
- **Ses torpilles** sont celles des joueurs (`surface_torpedo_lv0N`, 20 à 30 points de dégâts). Elles touchent
  comme celles d'un joueur ([`bots_tir.inc`](../mods/en-ligne/src/bots_tir.inc)) : la console de la cible prend
  le coup (`@eventMessageWeaponHitTorp` pour un joueur, `@torpedoHitOnNpcToOwner` pour un bot). Elles traversent
  leurs coéquipiers et leur tireur. Le tireur est signalé comme bot : le joueur de la console ne compte pas ses
  victimes.

Le niveau du serveur (`bots_level`, `server.bots.level`) règle les réflexes et la précision. Toutes les valeurs
sont dans `bots_ia.p` :

| Niveau | Regarde autour | Pause après rechargement | Erreur de visée | Voit venir les torpilles | Virages prévus |
|---|---|---|---|---|---|
| normal | toutes les 10 images | 40 images | 2° | 35 % | non |
| difficile (par défaut) | toutes les 6 images | 12 images | 0,6° | 80 % | oui |
| expert | toutes les 3 images | aucune | aucune | toujours | oui |

## Le bac à sable

*Avancement estimé : 80 % — interprète AMX, monde simple ; pas la carte du jeu ni sa physique des collisions.*

```sh
make pawncc bots                        # le compilateur Pawn 3.3, puis src/*.p -> mods/en-ligne/*.pasm
python3 tools/botsim.py                 # duel, close, walls, corner, retreat, dodge, melee, aux trois niveaux
python3 tools/botsim.py duel --level 3 --pitch-sign -1
```

`tools/botsim.py` assemble `bots_ia.pasm` dans le vrai `surface_sub.amx` du dump. Il en exécute le code, comme
amx.c de Pawn 3.3, dans un monde à lui : fond, blocs, sous-marins, et torpilles avec la physique du jeu. Les
natives (`worldClipLine`, `worldFindActors`, propriétés…) y sont simulées. Il compte les tirs, les touches et les
images passées contre la carte. Il signale toute faute de la machine (pile, mémoire, instruction inconnue).

Résultats (1 800 images, une minute de jeu) :

| Scénario | normal | difficile | expert |
|---|---|---|---|
| duel contre un joueur qui zigzague et change de profondeur | 40 % des tirs touchent | 67 % | 75 % |
| joueur qui tourne tout près | 30 % | 75 % | 75 % |
| derrière un mur de 6 000 unités | 33 % | 100 % | 80 % |
| coque basse, un joueur qui fonce sur lui (repli) | 43 %, joueur coulé | 80 %, coulé | 50 %, coulé |
| tiré dessus toutes les 3 s | 5 torpilles reçues | 0 | 0 |
| 4 bots contre 4 bots | 32 touches, 3 coulés | 31 touches, 2 coulés | 28 touches, 1 coulé |

Le pilote coûte environ 3 500 instructions AMX par image et par bot. Contre une cible qui va tout droit, il
touche à tous les coups. Des mesures dans le bac à sable ont fixé plusieurs choix :

- l'interception exacte, en formule fermée, a remplacé une simulation image par image six fois plus chère ;
- la prévision d'une plongée est limitée à 25 images ;
- le côté de contournement d'un mur reste le même tant que le passage est bouché ;
- l'inclinaison des torpilles est vérifiée sur leur troisième axe, quelle que soit la convention du moteur.
