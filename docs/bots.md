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

Le bot ne fait que ce qu'un joueur peut faire. Il pilote avec les mêmes commandes (manche de virage,
accélérateur, ballasts, tir), dans les mêmes limites. Le bac à sable vérifie chaque image : vitesse de virage,
vitesse de pointe, axe de chaque tir.

- **La physique d'un joueur** (`pscope_player.p func_12184`, `func_13494`) :
  - le taux de virage va vers `maxTurn × manche × facteur`, de 2 % par image quand on pousse le manche et de
    3,8 % quand on le lâche ; le facteur vaut √(vitesse avant) / 10, au moins 0,4, donc 0,4 aux vitesses d'un
    sous-marin ;
  - la poussée vaut `accélérateur × belowAccel` ; la traînée de 0,038 s'applique le long du sous-marin et en
    travers ;
  - la marche arrière se fait à demi-puissance (`periscope_move.p`) ;
  - le sous-marin freine un instant à chaque tir (`torpedoFireBrakeTime` images à `torpedoFireBrakeRate`) ;
  - le ballast agit sur la vitesse verticale (`diveRate`, `diveDrag`) ;
  - le nez s'incline avec la plongée (tangage → −0,1 × vitesse verticale) ;
  - un contact le repousse de 5 unités par image, comme un joueur.

  Ce sont les caractéristiques de son sous-marin (`bxml/pscope_plyNN_stats` et les tables `table_maxturn`,
  `table_below_accel`, `table_dive_rate`). Un bot du serveur a celles du sous-marin qu'il montre
  (`server.bots.sub<k>`), un bot du jeu celles du premier.
- **Les collisions** : un `@eventCollide` ajouté à `surface_sub` le repousse de la carte et des autres
  sous-marins, et retire la vitesse qui l'y enfoncerait. Il regarde aussi devant lui (`worldClipLine`, plusieurs
  caps) pour contourner un obstacle, toujours par le même côté tant que le passage est bouché. Il sonde le fond,
  et recule s'il n'a presque pas bougé pendant deux secondes.
- **Ce qu'il voit, comme un joueur** (`player_label.p func_32fc`, `func_305c`) : un ennemi à moins de 7 000
  unités, sans rien de la carte entre eux, et pas masqué. Ou un ennemi que son sonar a trouvé il y a moins de
  300 images, jusqu'à 15 000 unités. Rien d'autre : il ne voit pas à travers les murs et n'a pas la carte de tous
  les sous-marins. Il vise tout ennemi, joueur ou bot, de cette console ou d'une autre. Il préfère le plus proche,
  le plus abîmé, celui qu'il voit.
- **Le sonar d'un joueur** (`sonar.p func_414c`, `func_42d4`) : sans ennemi en vue, il émet de temps en temps,
  avec 120 images d'attente entre deux impulsions, et va vers ce qu'il a entendu, sinon fait le tour du milieu
  de la carte. Le sonar n'entend pas un sous-marin d'une autre console arrêté (accélérateur sous 0,05). Toutes
  les consoles voient son impulsion sur leur sonar (`last_sonar`), comme celle d'un joueur.
- **Le masqueur le rend aveugle** : un ennemi masqué (`masker` ou `masker_on`) n'est jamais vu, de près ni de
  loin. Si sa cible se masque, le bot la perd. Il ne sait que vers où elle allait : il va la chercher là
  pendant 8 s et peut y tirer une ou deux torpilles au jugé. Une torpille à tête chercheuse perd elle aussi sa
  cible (le jeu, `surface_torpedo_p_homing.p func_4800`).
- **La visée** : il vise là où la cible sera quand la torpille y arrivera. Il connaît la course exacte d'une
  torpille, 118,8 × (n − 100 × (1 − 0,99ⁿ)) unités en n images (`func_1778`, `func_2ef4`), plus la vitesse du
  sous-marin qu'elle garde au départ et qui s'amortit comme la sienne. Il suppose que la cible garde sa vitesse
  et son taux de virage (un virage régulier est un cercle). Comme un joueur, il ne peut que tourner sa coque :
  - la torpille part de son tube (`torpedoSpawnPoint`), dans l'axe du sous-marin, avec son tangage et sa
    vitesse (`periscope_move.p func_fbdc`) ;
  - pour viser plus haut ou plus bas, il monte ou plonge, ce qui incline son nez et le rapproche de la
    profondeur de la cible ;
  - il ne tire que si une torpille partie là, maintenant, passerait assez près de la cible ;
  - la ligne doit être dégagée, sans coéquipier à moins de 220 unités de la trajectoire ;
  - une cible qui change de sens de virage n'est visée que de près.
- **Le combat** : il garde ses distances (2 200 à 3 000 unités, 1 700 contre une cible agile), recule face à un
  ennemi trop proche et ne l'éperonne jamais. Une torpille qui va passer près de lui, il la voit venir : il
  s'écarte de sa trajectoire et change de profondeur, parce qu'une torpille garde sa profondeur.
- **Les temps d'attente d'un joueur** (`periscope_move.p`) :
  - entre deux torpilles, `torpedoFireInterval` de son sous-marin, plus 15 images ;
  - le rechargement, d'un coup, `torpedoReplenishTime` secondes après la dernière torpille, et seulement quand il
    n'en reste aucune ;
  - les armes, dont les têtes chercheuses, attendent 135 images après chaque tir, et la torpille suivante
    `torpedoFireInterval` + 15 images (`func_10e04` : le délai du jeu plus 15) ;
  - le masqueur attend 150 images après le précédent.
- **Torpilles à tête chercheuse** : aucune au départ. Comme un joueur, il n'en a qu'en ramassant les conteneurs
  qu'un sous-marin coulé laisse, 3 au plus. Ce sont celles des joueurs (`surface_torpedo_p_homing`, verrouillées
  par `@lockOnTarget`), tirées dans l'axe du sous-marin sur une cible suivie depuis 1,5 s. Il les tire sur une
  cible qui vire fort ou passe vite, ou quand il est abîmé.
- **Les conteneurs** : le jeu interdisait à ses sous-marins de les ramasser (`surface_item.p @eventCollide`).
  Le bot les ramasse comme un joueur, et va chercher celui qu'il voit quand il en a besoin. Une réparation rend
  un cinquième de sa coque, ou tout ce qui manque s'il manque moins de 20 ; une tête chercheuse s'ajoute à son
  stock. Toutes les consoles retirent le conteneur ramassé (`@botTakesItem`).
- **Coque basse** (moins de 40 %) : il garde sa cible et recule en tirant. Quand un ennemi approche, il passe sous
  son masqueur (`masker`, `masker_on` : 300 images pour 33,3 d'air) et s'enfuit en profondeur. Comme un joueur,
  il ne retrouve de l'air qu'en surface : trois masqueurs par vie au plus, et jamais plus de trois.
- **Ses torpilles** sont celles des joueurs (`surface_torpedo_lv0N`, 20 à 30 points de dégâts). Elles touchent
  comme celles d'un joueur ([`bots_tir.inc`](../mods/en-ligne/src/bots_tir.inc)) : la console de la cible prend
  le coup (`@eventMessageWeaponHitTorp` pour un joueur, `@torpedoHitOnNpcToOwner` pour un bot). Elles traversent
  leurs coéquipiers et leur tireur. Le tireur est signalé comme bot : le joueur de la console ne compte pas ses
  victimes.
- **Sa mort compte** : le jeu ne prévient que pour un bot coulé par une torpille (`@eventMessageAISubDead`). Il
  ne le fait pas pour un bot coulé par une explosion (`@explosionHitOnNpc`), et retrouve l'équipe du bot par son
  numéro de synchronisation. La bataille pouvait donc ne jamais finir. C'est maintenant le pilote du bot qui
  annonce sa mort, une fois, avec son équipe : toutes les consoles l'entendent (`@botDown`,
  [`bots_partie.p`](../mods/en-ligne/src/bots_partie.p)) et retirent le bot du compteur de son équipe.
- **Le replay de la victoire** : le jeu montre en fin de bataille la course de la torpille qui a coulé le
  dernier sous-marin de l'équipe perdante. Il l'apprend de la mort d'un joueur
  (`@scheduleCheckGameOver(nœud, heure, nœud et numéro de la torpille)`) et trouve l'équipe du mort par
  `player.<nœud>.team`. La mort d'un bot n'avait ni torpille ni nœud : quand un bot était le dernier coulé, donc
  quand les joueurs gagnaient, il n'y avait pas de replay. Désormais, chaque torpille qui touche un bot le dit à
  toutes les consoles (`@botHitBy`). La mort du bot est inscrite comme celle d'un joueur, avec cette torpille et
  un nœud de son équipe (`0x7b070000` + équipe).

  Quand aucune torpille ne l'a coulé, ou que la dernière remonte à plus de 5 s (il s'est jeté contre la carte),
  le replay le montre lui-même, comme celui d'un joueur (`pscope_player.p func_8d38`). Pour cela, il reste
  synchronisé 215 images après sa mort, comme une torpille après son explosion.
- **Un joueur pour le jeu** : le jeu reconnaît les joueurs à leur nœud réseau (`player.<nœud>.name`, `.team`).
  Chaque bot k en a un à lui, `0x7b070000` + k, avec son nom et son équipe
  ([`bots_partie.p`](../mods/en-ligne/src/bots_partie.p)). Il a donc ce qu'a un joueur :
  - « Vous avez touché <bot> ! » (`@pushTargetHitMessage`) et le marqueur de touche pour qui le touche ;
  - « <bot> vous attaque ! » (`@pushHitByShooterMessage`) pour le joueur qu'il touche ;
  - « <bot> a été coulé ! » pour tous, au lieu de « L'ennemi a été coulé ! » des sous-marins de l'ordinateur ;
  - le kill compté à son tireur (`incrementKills`) ;
  - le marqueur de touche du HUD n'apparaît plus quand un bot de cette console en touche un autre.
- **Mort comme un joueur** : il explose et disparaît d'un coup (`explosion_player_dead`), sans couler lentement
  pendant 6 s (`func_ba34`). Sur les autres consoles, sa copie explose comme celle d'un joueur.
- **Vie et dégâts d'un joueur** :
  - 100 points de vie, multipliés par la taille de l'équipe adverse sur la sienne quand la sienne est plus petite
    (`pscope_player.p func_14f60`) ;
  - le jeu ne comptait que les joueurs humains ; maintenant les bots sont comptés, pour les joueurs aussi
    ([`bots_joueur.pasm`](../mods/en-ligne/bots_joueur.pasm)) : seul contre 4 bots, un joueur a 400 points de vie,
    comme seul contre 4 joueurs ;
  - les dégâts d'un joueur (`@eventDamageTorp`, `@eventMessageExplosionHit`), où le jeu en donnait d'autres à ses
    sous-marins de l'ordinateur :

    | Coup | Joueur (et bot) | Sous-marin de l'ordinateur |
    |---|---|---|
    | torpille | ses dégâts | les mêmes |
    | torpille à tête chercheuse | 30 | 70 |
    | explosion | 5, jusqu'à 750 unités | 30, jusqu'à 300 |
    | après un coup (et au départ) | rien pendant 60 images | tout |
    | contact avec la carte ou un sous-marin | 2,5, une fois par seconde | rien |
    | torpille ou explosion d'un allié | rien (« Vous avez touché un allié ! ») | tout |

  - chaque coup est multiplié par le `damageRate` de son sous-marin, arrondi au-dessus ;
  - le spectateur voit sa jauge baisser (`lifecapacity`, lue par `hud.p @setTelecastPlayer`).
- **La fuite d'huile** (la fumée noire d'un sous-marin abîmé) apparaît sous 40 % de sa coque, comme pour un
  joueur (`netplay_dummy_sub.p` : `life < lifecapacity / 2,5`). Le jeu l'allumait sous 100 points, quelle que soit la
  coque.
- **Vu un instant sous son masqueur quand on le touche**, comme un joueur : `pscope_player.p func_a758` met le
  drapeau d'affichage 6 quand la vie baisse et `func_60b4` fait clignoter le sous-marin masqué. Personne ne le
  mettait pour `surface_sub`. Les bots voient aussi un instant un ennemi masqué qu'on vient de toucher.
- **Son nom en spectateur** : `world_map.p` nomme le sous-marin suivi par son `nodeid`. Celui d'un bot était le
  nœud de la console qui le pilote (« Position du bâtiment <votre pseudo> »). Maintenant, c'est son propre nœud,
  et chaque console connaît son nom dès son arrivée (`@botJoin`).

- **Le départ, comme un joueur.** Le jeu place chaque joueur sur un point de départ de la carte, le fichier
  `<carte>_p<emplacement>` (position et cap) : l'emplacement vaut (rang de sa console + `network.randomstartloc`)
  modulo 8, plus 1. Sur les cartes où les équipes partent de deux côtés (`teamSpawnIndex` de `mode_settings` :
  cartes 4, 7 et 10), c'est (`randomstartloc` + rang dans l'équipe) modulo 4, plus 1, et 4 de plus pour la
  seconde équipe (`mode_periscope.p` `func_540c` ; le décompilateur perd ces modulos, `sdiv.alt` suivi de
  `move.pri`). Les bots du jeu, eux, apparaissaient aux six points de ses sous-marins de l'ordinateur
  (`func_10120`), éparpillés sur la carte, coéquipiers compris. Désormais chaque bot prend, à sa première
  image, l'emplacement qui suit ceux des joueurs, comme le ferait un joueur de plus. Les points viennent des
  fichiers de la carte, recopiés à la construction du mod en `bxml/sdsw_spawn_<carte>[_p<n>]` (recette
  `[[bxml]] extract`, `mods/en-ligne/mod.toml`).
- **Les murs, avec toute la coque.** Un sous-marin de joueur est une capsule de 550 unités de long : son nez est
  à 300 unités de son centre. Le pilote sondait depuis le centre et ne ralentissait qu'à 300 unités d'un mur,
  c'est-à-dire nez contre la paroi. Pire : ce frein et la remontée devant une pente n'étaient appliqués qu'une
  image sur trois, quand `steerClear` tourne. Maintenant :
  - il regarde à 750 unités plus 80 fois sa vitesse (environ 1 500 à pleine vitesse), le temps que le virage
    s'installe ;
  - il vérifie aussi deux rayons le long de ses flancs (un rayon central rate un angle) ;
  - il ralentit selon la place devant son nez, et recule s'il va toucher ;
  - il respecte le plafond d'une grotte ;
  - ces limites valent à chaque image.
- **Pas deux combats pareils.**
  - Chaque bot tire son tempérament au départ : la distance qu'il aime (de 0,85 à 1,25 fois l'habituelle),
    son agressivité, le côté par lequel il tourne, la profondeur qu'il prend.
  - En combat, il change de manœuvre toutes les 2 à 10 secondes, au hasard et selon son tempérament. Il peut
    tenir sa distance face à la cible, tourner autour d'elle, se rapprocher, décrocher puis revenir, changer
    de profondeur, ou s'arrêter net : une torpille tirée sur sa vitesse passe alors devant lui.
  - Prêt à tirer et presque en face, il se tourne vers sa cible et tire, comme un joueur.
  - Quand ses coéquipiers combattent la même cible, il arrive par un autre côté.
- **Il apprend comment vous esquivez.** Après chaque tir, il regarde comment sa cible tourne 30 images plus
  tard, le temps de réaction d'un humain. Il en garde la moyenne par joueur, pour toute la session, dans
  `bots.dodge.<nœud>` : tous les bots de la console en profitent. À chaque tir, il choisit au hasard comment
  viser : la cible garde son virage, elle va tout droit, ou elle esquive comme d'habitude (après 15 images de
  réaction). Qui casse toujours du même côté se fait prendre ; qui apprend « le » tir des bots n'en voit plus un
  seul. Il esquive aussi lui-même de plusieurs façons : d'un côté ou de l'autre, en montant ou en descendant,
  à fond ou en freinant pour laisser passer la torpille devant.
- **Toujours dans les limites d'un joueur.** Tout passe par les mêmes commandes qu'avant (manche,
  accélérateur, ballasts, tir dans l'axe). Le bac à sable vérifie toujours chaque image.

## L'équipage

*Avancement estimé : 85 % — vérifié dans le bac à sable (notes, réparation, chargement de `crew_stats`) ; reste à
le voir dans Azahar.*

Le serveur donne à chaque bot un équipage, comme celui d'un joueur (`server.bots.crew<k>` : jusqu'à cinq
membres, 6 bits chacun). Le bot n'en garde que ce que son sous-marin accepte (`crewCount`, 1 à 5). Il lit les
membres dans les acteurs `crew_NN` que le script du joueur charge (`worlds/crew_stats`), et les charge lui-même
s'ils manquent. Au niveau normal, il prend 0 à 3 membres au hasard ; au niveau difficile, 2 à 5 ; au niveau
expert, 4 ou 5 membres qui n'ont que des bonus (`bots_crew = false` : pas d'équipage).

- **Les notes**, comme pour un joueur (`pscope_player.p customUpdateSubBonusStats`) : chaque membre ajoute ses
  points de virage, d'accélération, de plongée, de résistance, de torpilles et de rechargement à ceux du
  sous-marin. Les notes restent entre 1 et 10, le rechargement entre 1 et 30.
- **Les capacités**, aux valeurs du jeu :

  | Capacité | Membre | Pour le bot | Ce que fait le jeu |
  |---|---|---|---|
  | `lockOnLong` | 20 | voit et vise à 8 500 au lieu de 7 000 | `player_label.p func_32fc` |
  | `wideSonar` | 27 | sonar à 20 000 au lieu de 15 000 | `sonar.p func_42d4` |
  | `maskerConsumptionRate` | 25 | masqueur à 25 d'air au lieu de 33,3 | `periscope_move.p maskerActivate` |
  | `repair` | 30 | répare 1 % de sa coque toutes les 75 images (60 en v5200) | `pscope_player.p func_14ca8` |
  | `longMasker` (v5200) | 33 | masqueur de 450 images au lieu de 300 | `maskerActivate` |
  | `airRepairUp` (v5200) | 34 | air à 0,3 par image en surface au lieu de 0,2 | `periscope_move.p` |
  | `autoMasker` (v5200) | 36 | masqueur automatique quand une tête chercheuse le verrouille ou fonce sur lui ; il l'ôte au bout de 3 s s'il n'est pas abîmé | `@HomingLockOn` → `@autoMasker` |
  | `teamRepair` (v5200) | 37 | répare ses coéquipiers à moins de 2 000 | `pscope_player.p func_19744`, `func_1a424` |
  | `hideSonar` (v5200) | 39 | absent du sonar ennemi sous 40 de coque | `sonar.p func_5d6c` |

  Le serveur ne donne pas aux bots les membres dont la capacité ne sert qu'à un humain : l'écoute du morse
  ennemi (14), les alliés sur la carte (31) et, en v5200, la mine larguée avec le masqueur (32).
- **Et pour les autres.** Les capacités d'un joueur s'appliquent aux bots comme aux joueurs :
  - le sonar large et la longue portée de verrouillage d'un joueur trouvent les bots plus loin (le jeu) ;
  - la réparation d'équipe d'un joueur répare les bots de son équipe à moins de 2 000 ;
  - un joueur sous `hideSonar` et sous 40 de coque échappe au sonar des bots.

  Dans l'autre sens, la réparation d'équipe et le sonar masqué d'un bot passent par ses propriétés
  `teamRepair` et `targetHideSonar`, que le jeu synchronise. Le jeu ne les regardait que sur les copies des
  sous-marins des autres consoles : le mod étend ces deux tests aux sous-marins pilotés par la console
  (`pscope_player` 0x1981C et `sonar` 0x6150 en v5200, `0x80000` → `0x80004`). Ainsi, un bot répare aussi le
  joueur de sa propre console.

Le niveau du serveur (`bots_level`, `server.bots.level`) règle les réflexes et la précision, jamais ce que le
sous-marin peut faire. Toutes les valeurs sont dans `bots_ia.p` :

| Niveau | Regarde autour | Pause après rechargement | Tir passant au plus à | Voit venir les torpilles | Virages prévus | Manœuvres | Apprend vos esquives |
|---|---|---|---|---|---|---|---|
| normal | toutes les 10 images | 40 à 60 images | 90 unités de la cible | 35 % | non | tenir, tourner, profondeur ; 5 à 10 s | non |
| difficile (par défaut) | toutes les 6 images | 12 à 18 images | 60 unités | 85 % | oui | les six ; 2,5 à 6 s | oui |
| expert | toutes les 3 images | 0 | 45 unités | toujours | oui | les six ; 1,7 à 4,7 s | oui |

## Dans la mise à jour v5200

*Avancement estimé : 90 % — vérifié dans Azahar (v5200) : dégâts des bots, défaite, replay de la torpille, victoire
au temps ; la victoire par élimination de tous les bots reste à voir dans l'émulateur.*

Le code des bots est le même, traduit pour les scripts recompilés de la mise à jour
([mise-a-jour.md](mise-a-jour.md#des-scripts-dune-version-à-lautre)). Essayé dans Azahar, il cassait à
plusieurs endroits, tous corrigés :

- **La partie ne finissait pas quand le dernier bot coulait.** `@botDown` (`bots_partie.p`) s'arrêtait en route,
  après avoir baissé le compteur de l'équipe : ni « … a été coulé ! », ni kill, ni vérification de la fin de
  partie, ni replay. Deux causes : la v5200 n'a plus le texte `sub_sunk` (remplacé par `sub_sunk_01`, « %s a
  coulé %s ! », et `sub_sunk_02`), et ses scripts n'ont que 8 Ko de tas et de pile, contre 16 Ko dans le jeu.
  Le message suit maintenant la version (`#if SDSW_VERSION >= 5200`, constante de `tools/pawn2pasm.py`), et le
  code des mods redonne 16 Ko à chaque script qu'il modifie (`.heapstack`), sauf aux torpilles, chargées
  une par une.
- **Le joueur était invincible.** La v5200 ajoute un « tir ami » à `@eventDamageTorp` : pas de dégâts si
  l'équipe du nœud du tireur est celle du joueur. Le tir d'un sous-marin de l'ordinateur porte le nœud de sa
  console (le jeu y retrouve la torpille pour le replay) : seul contre les bots, c'est celle du joueur, qui
  ne prenait donc aucun dégât. Une torpille de bot qui arrive jusqu'au joueur est toujours ennemie (celles des
  coéquipiers passent au travers) : pour elle, plus de tir ami (accroche dans `mod.toml`).
- **« CPU a coulé <joueur> ! »** : `reportDeath` de la v5200 nomme le tireur, `name_npc` pour un sous-marin de
  l'ordinateur. Chaque console retient le bot qui a touché chaque joueur en dernier (`@botAttacks`) :
  « Dauphin a coulé Ronald ! ».
- **Le jeu s'arrêtait (« Exception Type: Break »)** au bout de quelques minutes : chaque torpille charge sa
  copie de son script (environ 70 Ko en v5200) dans les 24 Mo de mémoire principale, qui s'épuisaient avec sept
  bots qui tirent. Le mod `correctifs` passe la mémoire principale à 26 Mo, pour les deux versions.
- **Les caractéristiques des sous-marins 24 à 36** : un bot qui en montrait un prenait celles du premier.
- **La durée** : les batailles contre les bots durent `duration`, comme les autres (`bots_duration` est retirée).

Pour tester : `tools/botsim.py --version v5200` (le pilote dans le bac à sable), puis Azahar avec un serveur de
test (`bots_format = "1v1"` : le bot doit couler le joueur, la défaite et le replay suivre).

## Le bac à sable

*Avancement estimé : 80 % — interprète AMX, monde simple ; pas la carte du jeu ni sa physique des collisions.*

```sh
make pawncc bots                        # le compilateur Pawn 3.3, puis src/*.p -> mods/en-ligne/*.pasm
python3 tools/botsim.py                 # duel, close, walls, corner, canyon, cave, retreat, dodge, masker, habit,
                                        # melee, spawn, crew, aux trois niveaux
python3 tools/botsim.py duel --level 3 --pitch-sign -1
```

`tools/botsim.py` assemble `bots_ia.pasm` dans le vrai `surface_sub.amx` du dump. Il en exécute le code, comme
amx.c de Pawn 3.3, dans un monde à lui : fond, blocs, sous-marins, et torpilles avec la physique du jeu. Les
natives (`worldClipLine`, `worldFindActors`, propriétés…) y sont simulées. Il compte les tirs, les touches et les
images passées contre la carte. Il signale tout mouvement qu'un joueur ne pourrait pas faire : vitesse de virage
au-delà de 0,4 × `maxTurn`, vitesse au-delà de `belowAccel / linDrag`, torpille partie hors de l'axe du
sous-marin. Il signale toute faute de la machine (pile, mémoire, instruction inconnue).

Le monde du bac à sable donne aux sous-marins la coque d'un joueur, une capsule de 550 unités de long (cinq
sphères le long de l'axe). L'ancienne version du bac à sable n'avait qu'une sphère de 110 unités au centre : elle
ne voyait pas le nez du sous-marin heurter les murs.

Résultats (1 800 images, une minute de jeu) :

| Scénario | normal | difficile | expert |
|---|---|---|---|
| duel contre un joueur qui zigzague et change de profondeur | 43 % des tirs touchent | 67 % | 100 % |
| joueur qui tourne tout près | 25 % | 80 % | 80 % |
| derrière un mur de 6 000 unités | 100 % | 100 % | 100 % |
| canal en zigzag, cible au bout | 100 % | 100 % | 80 % |
| grotte au plafond bas | 57 % | 100 % | 100 % |
| joueur qui casse toujours du même côté (`habit`) | 80 % | 80 % | 80 % |
| coque basse, un joueur qui fonce sur lui : il recule en tirant | joueur coulé en 22 s | en 17 s | en 15 s |
| joueur masqué 10 s | perdu de vue, 1 tir au jugé | 2 tirs au jugé | 1 tir au jugé, aucune touche |
| 4 bots contre 4 bots | 19 touches | 22 touches | 22 touches |
| départ (carte 1, un joueur contre 4 bots) | emplacements 5 à 8, le joueur au 4 | | |
| équipage (5 membres, dont réparation) | +46 de coque en une minute | | |

Images passées contre la carte, au niveau expert, avec la nouvelle capsule :

| Scénario | ancien pilote | nouveau pilote |
|---|---|---|
| lancé à pleine vitesse vers un coin (`corner`) | 30 | 0 |
| murs et rochers (`walls`) | 3 | 0 |
| grotte (`cave`) | 11 | 5 |
| canal (`canyon`) | 0 | 0 |

Sur tous les scénarios et à tous les niveaux, le bac à sable n'a relevé aucun mouvement ni aucun tir impossible pour
un joueur. Tous les tirs partent dans l'axe du sous-marin, et les vitesses de virage et de pointe restent sous
celles de son sous-marin.

Le pilote coûte de 2 000 à 4 500 instructions AMX par image et par bot. Des mesures dans le bac à sable ont fixé
plusieurs choix :

- l'interception exacte, en formule fermée, a remplacé une simulation image par image six fois plus chère ;
- la prévision d'une plongée est limitée à 25 images ;
- le côté de contournement d'un mur reste le même tant que le passage est bouché ;
- pour viser en hauteur, il monte ou plonge : son nez s'incline et la torpille part dans son axe ;
- le manche est réglé pour suivre un cap qui bouge (l'erreur tombe sous 0,01 rad).
