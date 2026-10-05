# Une IA qui joue comme un bon joueur : estimation

Les bots actuels (`mods/en-ligne/bots_*.pasm`) sont des bots **écrits à la main** : ils visent l'ennemi le plus
proche là où il sera et tirent dès qu'ils sont alignés. Ils sont dangereux de près mais prévisibles. Cette page
estime ce qu'il faudrait pour une IA **apprise**, aussi forte qu'un bon joueur de Sub Wars (le haut du
classement de l'époque : bonne visée à longue distance, esquives, sonar et masqueur au bon moment, jeu
d'équipe). Ce sont des ordres de grandeur, pas des promesses.

## Ce que l'IA doit apprendre

- **Observer** : sa position, son cap, sa profondeur, sa vitesse ; ce que montrent le sonar et le périscope
  (ennemis visibles, torpilles en approche) ; l'état de son équipe. On lit cet état dans le jeu (variables des
  scripts, acteurs) plutôt que dans l'image : c'est 10 à 100 fois moins coûteux à apprendre que des pixels.
- **Agir** 5 à 10 fois par seconde : moteur (avant/arrière), barre, plongée, tir, sonar, masqueur.
- **Gagner** : couler, ne pas être coulé, rester en vie avec l'équipe jusqu'à la fin du temps.

Points de comparaison publiés : les agents de *Capture the Flag* de DeepMind (Quake III, équipes de 2, vision
en pixels) ont dépassé de bons joueurs humains au bout de **plusieurs centaines de milliers de parties** de 5
minutes ; OpenAI Five
(Dota 2, bien plus complexe) a joué l'équivalent de dizaines de milliers d'années. Sub Wars est plus lent, avec
moins d'actions et une carte plus simple ; avec un état lu dans le jeu au lieu de pixels, il faut beaucoup
moins d'expérience.

## Combien de parties

| Niveau visé | Parties d'entraînement (10 min, 4 contre 4, l'IA joue les 8 sous-marins) | Temps de jeu équivalent |
|---|---|---|
| Bat les bots du jeu | 1 000 à 3 000 | 1 à 3 semaines de jeu continu |
| Joueur moyen | 5 000 à 20 000 | 1 à 4 mois |
| **Bon joueur** | **20 000 à 100 000** | **4 mois à 2 ans** de jeu continu |

Repères : un humain devient bon en quelques centaines à deux mille parties ; l'IA, partie de zéro, en a besoin
de 10 à 100 fois plus, mais elle les joue bien plus vite qu'en temps réel. Une partie de 10 minutes, c'est
18 000 images de simulation ; à 7 ou 8 décisions par seconde, environ 40 000 décisions pour les 8 sous-marins :
le bon niveau représente de l'ordre de **1 à 4 milliards de décisions**.

## Combien de temps

Tout dépend de la vitesse à laquelle on peut faire jouer le jeu.

**Dans le vrai jeu (Azahar)** : un émulateur tourne à 1 à 3 fois le temps réel sur un bon PC, et chaque console
ne pilote qu'un sous-marin ; une partie à 8 IA demande 8 émulateurs (environ 1,2 Go de mémoire chacun). Sur un
PC de 16 cœurs et 32 Go : 15 à 25 parties par heure, soit **1 à 9 mois de calcul sans arrêt** pour le bon
niveau. Trop lent pour tout l'entraînement, mais c'est le bon outil pour la fin (voir ci-dessous).

**Dans un simulateur à nous** : recoder la physique du jeu (déplacement des sous-marins, torpilles, dégâts,
collisions avec les cartes, sonar) d'après les scripts décompilés (`decomp/scripts/pscope_player.p`,
`periscope_move.p`, `surface_torpedo.p` ; formats des cartes dans [formats.md](formats.md)), sans affichage et
vectorisé sur carte graphique. Il tourne des milliers de fois plus vite que le temps réel :

| Étape | Durée estimée |
|---|---|
| Simulateur fidèle au jeu, vérifié contre le jeu (mêmes trajectoires, mêmes touches) | 1 à 3 mois de développement |
| Entraînement par auto-apprentissage (PPO, ligues d'adversaires) jusqu'au bon niveau | **2 à 7 jours** sur une carte graphique récente (ou 30 à 150 € de location de GPU) |
| Passerelle vers le vrai jeu : l'IA lit l'état et envoie les commandes d'une console émulée | 2 à 4 semaines |
| Ajustement dans le vrai jeu (écarts entre simulateur et jeu) | 1 000 à 5 000 parties, 1 à 2 semaines de calcul |

Soit **3 à 5 mois** en tout pour une personne, dont l'essentiel en développement. Le PC de développement
actuel (7 Go de mémoire, sans carte graphique dédiée) ne suffit pas pour l'entraînement : il faudrait un PC
avec une carte graphique ou un serveur loué quelques jours.

## Variante plus rapide : imiter de bons joueurs

Enregistrer quelques centaines de parties de bons joueurs (le mod peut journaliser leurs commandes et l'état du
jeu), apprendre d'abord à les imiter, puis améliorer l'IA par auto-apprentissage. On atteint un niveau correct
plus vite (quelques milliers de parties au lieu de dizaines de milliers), mais il faut des joueurs et des
enregistrements, qui n'existent plus depuis la fermeture des serveurs de Nintendo.

## Et pour de « vrais joueurs » bots

Une IA apprise pilote un sous-marin exactement comme un joueur (mêmes commandes, même physique, mêmes
collisions), ce qui règle les limites des bots actuels, qui reprennent les sous-marins simplifiés des missions
du jeu. La suite logique : la faire tourner sur le serveur, branchée à des consoles émulées sans écran qui
rejoignent les parties comme des joueurs, ou directement dans le portage PC.
