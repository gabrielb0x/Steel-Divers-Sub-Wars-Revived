# Une IA entraînée aussi forte qu'un joueur : combien de parties ?

Les bots actuels du serveur (`mods/en-ligne/bots_*.pasm`) sont **écrits à la main** : ils visent l'ennemi le plus
proche là où il sera et tirent dès qu'ils sont alignés. Cette page estime ce qu'il faudrait pour une IA
**apprise** (apprentissage par renforcement), aussi forte qu'un joueur humain, en local et en ligne. Ce sont des
ordres de grandeur, pas des promesses.

## En bref

*Avancement estimé : 0 % — aucune IA n'est entraînée ; cette page n'est qu'une estimation.*

Parties de 10 minutes en 4 contre 4, l'IA pilotant les 8 sous-marins (elle joue contre elle-même) :

| Joueur à égaler | Parties d'entraînement | Temps de jeu équivalent (une partie à la fois) |
|---|---|---|
| **Joueur en local**, occasionnel (entre amis, quelques dizaines de parties) | **3 000 à 10 000** | 3 semaines à 2 mois et demi |
| **Joueur en ligne moyen** (milieu du classement de l'époque) | **15 000 à 40 000** | 3 mois et demi à 9 mois |
| **Bon joueur en ligne** (haut du classement : visée de loin, esquives, sonar et masqueur au bon moment, jeu d'équipe) | **40 000 à 150 000** | 9 mois à 3 ans |

Les règles sont les mêmes en local et en ligne (mêmes sous-marins, mêmes cartes) : seule change la force des
humains à égaler. En local, on joue surtout entre amis peu entraînés ; en ligne, les joueurs réguliers avaient
des centaines de parties derrière eux. Le temps de calcul réel est bien plus court que le temps de jeu, parce
que l'IA joue plusieurs parties à la fois et plus vite que le temps réel (voir plus bas).

## Ce que l'IA doit apprendre

*Avancement estimé : 10 % — on sait où lire l'état du jeu (variables des scripts, acteurs) et quelles commandes
envoyer ; rien n'est branché.*

- **Observer** : sa position, son cap, sa profondeur, sa vitesse ; ce que montrent le sonar et le périscope
  (ennemis visibles, torpilles en approche) ; l'état de son équipe, son air et ses torpilles. On lit cet état dans
  le jeu (variables des scripts, acteurs) plutôt que dans l'image : c'est 10 à 100 fois moins coûteux à apprendre
  que des pixels.
- **Agir** 7 à 8 fois par seconde (une décision toutes les 4 images) : moteur (avant/arrière), barre, plongée,
  direction du périscope, tir, torpille guidée, sonar, masqueur.
- **Gagner** : couler, ne pas être coulé, rester en vie avec l'équipe jusqu'à la fin du temps.

## D'où viennent ces nombres

*Avancement estimé : 100 % pour l'estimation (hypothèses et comparaisons ci-dessous) ; à vérifier par un premier
entraînement.*

- **Une partie, c'est beaucoup d'expérience** : 10 minutes à 30 images par seconde, 18 000 images ; à une décision
  toutes les 4 images, 4 500 décisions par sous-marin, 36 000 pour les 8. Le niveau « bon joueur en ligne »
  représente 1,5 à 5 milliards de décisions, l'ordre de grandeur des entraînements réussis sur des jeux d'action
  de cette taille.
- **Comparaisons publiées** : les agents de *Capture the Flag* de DeepMind (Quake III, équipes de 2, vision en
  pixels) ont dépassé de bons joueurs humains au bout d'environ 450 000 parties de 5 minutes ; OpenAI Five
  (Dota 2, bien plus complexe) a joué l'équivalent de dizaines de milliers d'années. Sub Wars est plus lent, a
  moins d'actions et des cartes plus simples, et l'IA y lirait l'état du jeu au lieu de pixels : il lui faut 3 à
  10 fois moins de parties que dans *Capture the Flag* pour le haut niveau.
- **Comparaison avec un humain** : un débutant devient un joueur correct en quelques dizaines de parties et un bon
  joueur en ligne en quelques centaines à deux mille ; une IA partie de zéro a besoin de 10 à 100 fois plus
  d'expérience qu'un humain, qui arrive avec son sens de l'espace et des jeux déjà appris.

## Combien de temps de calcul

*Avancement estimé : 0 % — ni passerelle vers le jeu ni simulateur.*

Tout dépend de la vitesse à laquelle on peut faire jouer le jeu.

**Dans le vrai jeu (Azahar)** : un émulateur tourne à 1 à 3 fois le temps réel sur un bon PC, et chaque console
ne pilote qu'un sous-marin ; une partie à 8 IA demande 8 émulateurs (environ 1,2 Go de mémoire chacun). Sur un
PC de 16 cœurs et 32 Go : 15 à 25 parties par heure.

| Joueur à égaler | Calcul sans arrêt dans Azahar |
|---|---|
| Joueur en local | 5 jours à 4 semaines |
| Joueur en ligne moyen | 3 semaines et demie à 4 mois |
| Bon joueur en ligne | 2 à 14 mois |

**Dans un simulateur à nous** : recoder la physique du jeu (déplacement des sous-marins, torpilles, dégâts,
collisions avec les cartes, sonar) d'après les scripts décompilés (`decomp/scripts/pscope_player.p`,
`periscope_move.p`, `surface_torpedo.p` ; formats des cartes dans [formats.md](formats.md)), sans affichage et
vectorisé sur carte graphique. Il tourne des milliers de fois plus vite que le temps réel :

| Étape | Durée estimée |
|---|---|
| Simulateur fidèle au jeu, vérifié contre le jeu (mêmes trajectoires, mêmes touches) | 1 à 3 mois de développement |
| Entraînement jusqu'au joueur en local | quelques heures sur une carte graphique récente |
| Entraînement jusqu'au bon joueur en ligne (auto-apprentissage, ligues d'adversaires) | 2 à 7 jours (ou 30 à 150 € de location de GPU) |
| Passerelle vers le vrai jeu : l'IA lit l'état et envoie les commandes d'une console émulée | 2 à 4 semaines |
| Ajustement dans le vrai jeu (écarts entre simulateur et jeu) | 1 000 à 5 000 parties, 1 à 2 semaines de calcul |

Soit **3 à 5 mois** en tout pour une personne, dont l'essentiel en développement. Le PC de développement
actuel (7 Go de mémoire, sans carte graphique dédiée) ne suffit pas pour l'entraînement : il faudrait un PC
avec une carte graphique ou un serveur loué quelques jours.

## Plus vite : imiter de vrais joueurs

*Avancement estimé : 5 % — le serveur et le mod en ligne existent ; aucun enregistrement de partie.*

Notre serveur fait de nouveau jouer des humains en ligne : avec leur accord, le mod pourrait enregistrer leurs
commandes et l'état du jeu. Quelques centaines de parties de bons joueurs suffisent pour apprendre d'abord à
les imiter, puis l'auto-apprentissage améliore l'IA : on atteint le niveau d'un joueur en local en **quelques
centaines de parties** d'entraînement, et celui d'un bon joueur en ligne en **5 000 à 20 000** au lieu de
40 000 à 150 000. Il n'existe aucun enregistrement de l'époque des serveurs de Nintendo.

## Et pour des bots comme de vrais joueurs

*Avancement estimé : 80 % — les bots écrits à la main pilotent maintenant comme des joueurs ([bots.md](bots.md)) ;
une IA apprise reste à faire.*

Les bots en ligne ont désormais la physique, les collisions et les armes d'un joueur, et un pilote écrit à la
main ([bots.md](bots.md)) : visée là où sera la cible, esquive, repli sous le masqueur. Une IA apprise irait plus
loin (tactique d'équipe, sonar, ruses), avec les mêmes commandes. La suite logique : la faire tourner sur le
serveur, branchée à des consoles émulées sans écran qui rejoignent les parties comme des joueurs, ou directement
dans le portage PC.
