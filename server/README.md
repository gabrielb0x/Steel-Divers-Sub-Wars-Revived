# Serveur en ligne

Serveur de remplacement pour le mode en ligne de Steel Diver: Sub Wars : connexion des joueurs, recherche de
partie (matchmaking) et aide à la connexion directe entre consoles (NAT traversal). Les parties elles-mêmes se
jouent de console à console (Pia, en P2P) : le serveur ne voit passer que la tenue des salons.

Écrit en Python (3.11 ou plus récent), **sans aucune dépendance** : la bibliothèque standard suffit. Tout ce qu'il
implémente vient de la rétro-ingénierie du jeu (EUR v0) ; le détail est dans [../docs/online.md](../docs/online.md).

**Vérifié avec le vrai jeu** : deux instances d'Azahar équipées du mod [`en-ligne`](../mods/en-ligne/mod.toml)
se connectent, se retrouvent dans le même salon et lancent une bataille ensemble.

## Lancer le serveur

*Avancement estimé : 100 %.*

```sh
cd server
python3 -m sdsw_server            # les deux royaumes de serveur.toml + la détection de NAT
python3 -m sdsw_server --realm emulateur -v      # un seul royaume, journal détaillé (-vv : paquets)
```

## Deux royaumes : émulateur et PC

*Avancement estimé : 90 % — le royaume PC est prêt côté serveur mais attend le portage PC.*

Le fichier [`serveur.toml`](serveur.toml) décrit deux « royaumes » totalement séparés (comptes, salons) :

| Royaume | Joueurs | Authentification | Serveur sécurisé |
|---|---|---|---|
| `emulateur` | Azahar + mod `en-ligne` | UDP 61000 | UDP 61001 |
| `pc` | portage PC (à venir) | UDP 61010 | UDP 61011 |

Les deux tournent dans le même processus et partagent la détection de NAT (UDP **10025** et **10125**, ports fixés
par le jeu). Le portage PC exécutera le même code réseau que le jeu (NEX et Pia), donc le même protocole : seul
le port qu'il vise change. Pour faire jouer tout le monde ensemble, il suffirait de lui donner le port du royaume
`emulateur`.

## Bots et triche

*Avancement estimé : 70 % — anti-triche et séparation des tricheurs faits ; bots à rendre plus humains (collisions entre eux, combats entre bots, déplacements naturels).*

Chaque royaume a ses options de partie dans `serveur.toml` (le lanceur les affiche et les modifie, onglet
**Serveur**, « Configuration du serveur ») :

* **`max_players`** (2 à 8) : nombre de joueurs humains par partie. La console hôte complète chaque équipe à
  4 sous-marins avec les bots du jeu (`mode_periscope` › `@setNpc`) : limiter les humains donne plus de bots.
* **`duration`** (1 à 30 minutes, 10 par défaut comme le jeu) : durée d'une bataille en ligne. Le serveur
  l'envoie à chaque console quand elle cherche une partie (`server.duration`) et le mod
  [`en-ligne`](../mods/en-ligne/mod.toml) la met à la place des 600 secondes fixées par le jeu
  (`mode_periscope` › `inputProperties`) ; un mod en-ligne plus ancien garde 10 minutes. Les batailles contre
  les bots durent autant (l'ancienne option `bots_duration` est ignorée).
* **Bots pour un joueur seul** (`bots = true`, avec le mod [`en-ligne`](../mods/en-ligne/mod.toml) à jour) :
  un joueur resté seul dans une partie `bots_delay` secondes (60) joue contre des bots. Le jeu d'origine
  attend sans fin un adversaire ; ici le serveur envoie au jeu les réglages de la partie, et les bots
  **rejoignent le salon comme des joueurs**, un par un (nom, sous-marin, niveau, prêts), puis le compte à
  rebours (`bots_countdown` secondes) lance la bataille. En bataille ils ont la coque et les couleurs d'un
  vrai sous-marin, leur nom et leur niveau au-dessus d'eux (pas « CPU »), ils comptent dans les compteurs
  d'équipe et pour la victoire, et la caméra du spectateur peut les suivre. Options :
  * `bots_format` : les deux équipes, `"4v4"` (vous et 3 bots contre 4 bots), `"1v4"` (seul contre 4),
    `"2v3"`… de 1 à 4 par équipe ; si un autre joueur arrive avant la bataille, il joue avec vous et les bots
    complètent ;
  * `bots_map` : `"aleatoire"` ou le numéro d'une carte (1, 2, 4 à 10 ; le lanceur affiche leurs noms, lus
    dans votre jeu) ;
  * `bots_level` : `"normal"`, `"difficile"` ou `"expert"` ; les bots pilotent comme des joueurs (physique et
    caractéristiques de leur sous-marin, collisions, visée là où sera la cible, esquive, torpilles à tête
    chercheuse, masqueur et repli quand leur coque est basse : `mods/en-ligne/src/bots_ia.p`), le niveau
    règle leurs réflexes et leur précision (expert : visée parfaite) ; vaut pour tous les bots des parties
    en ligne ;
  * `bots_crew` : `true` (par défaut), chaque bot prend un équipage comme un joueur (jusqu'à 5 membres, autant
    que son sous-marin en accepte), qui change ses notes et lui donne ses capacités (portée de verrouillage,
    sonar large, masqueur moins cher ou plus long, réparation…) ; au niveau expert, des membres qui
    n'ont que des bonus ([bots.md](../docs/bots.md#léquipage)) ;
  * `bots_names` : les noms des bots (au moins 7, 10 caractères au plus), tirés au hasard à chaque partie.

  Comment le serveur parle au jeu : par des notifications NEX à lui (types 999001 et 999002) que le mod
  `en-ligne` transforme en variables de script du jeu (`server.bots.*`) ; détails dans
  [../docs/online.md](../docs/online.md#8-serveur--jeu--les-variables-du-mod).
* **`cheats`** : que faire des joueurs dont le mod contient [la triche](../mods/triche/mod.toml) ou des
  [caractéristiques de sous-marins modifiées](../mods/specs/mod.toml) (leur jeton le déclare : drapeaux
  `triche` et `specs`) : `"separes"` (par défaut : ils ne rencontrent que d'autres tricheurs), `"autorises"`
  (ils jouent avec tout le monde) ou `"refuses"` (connexion refusée). Le mod [`premium`](../mods/premium/mod.toml)
  (drapeau `premium`) n'est pas de la triche : il donne ce que les joueurs premium avaient. La triche elle-même
  est dans le jeu, pas dans le serveur ; un jeu modifié autrement peut toujours mentir, comme dans tout jeu
  en P2P. Pour un serveur où tout le monde triche, mettre `cheats = "autorises"`.
* **Anti-triche** (sauf avec `cheats = "autorises"`, et pas dans les parties de tricheurs) : le serveur
  demande au mod `en-ligne` de chaque joueur de surveiller son propre sous-marin en bataille — dégâts
  annulés sans raison du jeu (invincibilité), torpilles qui ne baissent pas, tirs à moins d'une seconde
  d'intervalle (aucun sous-marin ne tire plus vite que toutes les 2,8 s), vitesse au-delà de 20 unités par
  image pendant 3 secondes (le plus rapide plafonne à 14,2). Au premier signe, le jeu **quitte la bataille**
  comme avec le bouton « quitter » du jeu (le tricheur disparaît de la partie des autres) et garde ce renvoi
  dans sa sauvegarde ; à sa recherche de partie suivante, il le dit au serveur, qui le met avec les
  tricheurs (`separes`) ou le tient à l'écart (`refuses`) pendant `anticheat_ban` minutes (30 par défaut ;
  liste dans `data/<royaume>/exclusions.json`, chaque renvoi n'est sanctionné qu'une fois). Cela attrape
  les codes de triche d'Azahar et les mods de triche dont on a caché le drapeau ; un jeu dont on a retiré la
  surveillance y échappe, comme dans tout jeu en P2P sans serveur de partie. Dans Azahar sans les fichiers
  système de la console, le jeu ne peut pas afficher le code d'erreur d'un joueur tenu à l'écart : sa
  recherche revient simplement au menu.

## Page d'état et bannissements

*Avancement estimé : 100 %.*

* **Page d'état** : avec `status_port = 8730` (section `[server]` de `serveur.toml`), le serveur publie en HTTP
  une page (`http://<adresse>:8730/`) et sa version JSON (`/status.json`) : joueurs connectés, comptes,
  options, et les parties en cours (nombre de joueurs, ouverte ou commencée, partie de tricheurs, depuis
  combien de temps). Aucun identifiant de joueur n'y figure. Ouvrir ce port TCP pour la rendre publique.
* **Bannir un joueur** : son identifiant (le journal affiche `login pid …` à chaque connexion) sur une ligne de
  `data/<royaume>/bannis.txt` (les lignes qui commencent par `#` sont des commentaires). Le fichier est relu à
  chaque connexion : pas besoin de redémarrer, la connexion suivante de ce joueur est refusée.

## Jouer avec des amis éloignés

*Avancement estimé : 85 % — UPnP et STUN vérifiés ; pas encore de vraie partie entre deux maisons ni de relais pour les NAT stricts.*

Le plus simple : le lanceur (`python3 subwars.py`, onglet **Serveur**). « Lancer le serveur » arrête d'abord un
serveur déjà lancé sur l'ordinateur (par un ancien lanceur, un terminal), puis affiche l'**adresse à donner aux
amis**. Chaque ami entre cette adresse dans « Rejoindre le serveur d'un ami » (« Tester » vérifie que le serveur
répond depuis chez lui), puis installe le mod **Jeu en ligne** avec elle. Celui qui héberge joue sur le même
ordinateur avec l'adresse `127.0.0.1` (le réglage par défaut du mod).

Ce que fait le serveur pour être joignable depuis Internet :

* **Adresse publique** : `public_address = "auto"` (par défaut) demande son adresse Internet à la box (UPnP),
  sinon à un serveur STUN public (Google, Cloudflare). On peut aussi l'écrire : une IP, ou un nom
  (`monserveur.duckdns.org`, pratique si l'adresse change ; le jeu résout les noms).
* **Ports ouverts sur la box** : avec `upnp = true` (par défaut), le serveur demande à la box de lui rediriger ses
  ports UDP (61000-61001, 61010-61011, 10025, 10125, et le port TCP de la page d'état s'il y en a une), renouvelle
  ces redirections tant qu'il tourne et les retire quand il s'arrête. Vérifié avec une box.
* **Le joueur qui héberge** : sa console se connecte par `127.0.0.1`, une adresse qui ne veut rien dire pour un
  ami. Or, pour rejoindre une partie, une console compare l'adresse publique de l'hôte à la sienne : la même,
  elle passe par le réseau local ; une autre, par l'adresse publique. Le serveur présente donc les joueurs de son
  propre réseau sous son adresse publique, et redirige sur la box le port de leur jeu (Pia, pris au hasard entre
  49152 et 65534) le temps qu'ils sont connectés. Sans cette redirection, les box qui tournent sous Linux (la
  plupart) font échouer la connexion directe : les premiers paquets de l'ami y créent une entrée qui force un
  autre port pour la réponse.

Sans UPnP (désactivé sur la box, ou `upnp = false`), il faut rediriger à la main vers l'ordinateur du serveur :
UDP 61000-61001 (et 61010-61011 pour le royaume PC), 10025 et 10125, et, pour jouer soi-même sur cet ordinateur,
la plage UDP 49152-65535 (le port du jeu change à chaque connexion). Le serveur réessaie l'UPnP toutes les 20 minutes.

### Quand la box ne suffit pas

* **IPv4 partagée** : la box n'a qu'une partie des ports (« IPv4 partagée » chez certains opérateurs) et refuse les redirections
  hors de sa plage, ou elle est elle-même derrière le NAT de l'opérateur (certaines offres mobiles, satellite).
  Le lanceur affiche les redirections refusées, et signale un « autre NAT devant la box » quand l'adresse de la
  box n'est pas celle que voit Internet. Beaucoup d'opérateurs donnent une adresse IPv4 complète sur demande.
* **Réseau privé virtuel** (ZeroTier, Tailscale, Radmin VPN…) : tous les joueurs rejoignent le même réseau, et
  tout le monde, y compris celui qui héberge, construit le mod avec l'adresse du serveur **sur ce réseau**. Aucun
  port à ouvrir. Le serveur donne à chacun l'adresse par laquelle il l'a joint.
* **Serveur sur une machine louée** (VPS) : lancer `python3 -m sdsw_server` dessus et ouvrir ses ports UDP dans
  son pare-feu ; tous les joueurs sont alors « éloignés », y compris celui qui le loue.

La partie elle-même reste de console à console : si les deux NAT des joueurs sont stricts (symétriques), la
connexion directe peut échouer même avec un serveur joignable.

### Vérifier depuis chez un ami

```sh
cd server && python3 -m sdsw_server.testclient --probe <adresse>[:61000]
```

envoie ce qu'envoie la console avant de se connecter (début de connexion aux deux serveurs, détection de NAT) et
dit si le serveur répond, et sous quelle adresse il voit l'ami. C'est le bouton « Tester » du lanceur.

### Lancé par le lanceur

Le serveur écrit `data/serveur.json` pendant qu'il tourne (processus, ports, adresse publique, redirections de la
box), que le lanceur affiche ; `--exit-with-stdin` l'arrête proprement (redirections retirées) quand le lanceur
qui l'a démarré disparaît, même tué : plus de serveur oublié qui garde les ports.

## Comptes

*Avancement estimé : 100 %.*

Pas d'inscription : sur 3DS, le mot de passe venait des serveurs de comptes de Nintendo. Le mod donne à chaque
joueur un identifiant (principal ID) et un mot de passe aléatoires, créés quand il construit le mod ; le jeton
d'authentification contient la clé Kerberos dérivée du mot de passe. Le serveur enregistre l'identifiant à sa
première connexion et exige ensuite la même clé (`data/<royaume>/accounts.sqlite3`).

Aucune donnée de jeu n'est stockée : le jeu n'utilise pas de classements ni de stockage côté serveur.

## Organisation du code

*Avancement estimé : 100 %.*

| Fichier | Rôle |
|---|---|
| `sdsw_server/prudp.py` | transport PRUDP v1 : poignée de main, signatures HMAC, RC4, fiabilité, fragments |
| `sdsw_server/rmc.py` | appels de méthodes (RMC), dans les deux sens |
| `sdsw_server/streams.py`, `ddl.py` | sérialisation NEX et structures du jeu (MatchmakeSession, critères…) |
| `sdsw_server/crypto.py` | RC4, chiffrement Kerberos, dérivation de clé |
| `sdsw_server/realm.py` | serveur d'authentification (TicketGranting) et serveur sécurisé (SecureConnection, NATTraversal, MatchMaking, MatchmakeExtension) |
| `sdsw_server/matchmaking.py` | salons, notifications, bots pour un joueur seul |
| `sdsw_server/config.py` | options de `serveur.toml`, lues et réécrites avec leurs commentaires (lanceur) |
| `sdsw_server/natcheck.py` | détection de NAT de Pia (serveurs « nncs ») |
| `sdsw_server/internet.py` | adresse publique, redirections de la box, joueurs du réseau du serveur |
| `sdsw_server/upnp.py`, `stun.py` | clients UPnP (box) et STUN, bibliothèque standard seule |
| `sdsw_server/accounts.py` | comptes |
| `sdsw_server/status.py` | page d'état (HTTP) |
| `sdsw_server/testclient.py` | client qui se comporte comme le jeu, pour tester sans console ; `--probe` |

## Tests

*Avancement estimé : 90 % — 40 tests automatiques ; les essais avec le vrai jeu restent manuels.*

```sh
cd server
python3 -m unittest discover -s tests -t . -v      # formats, cryptographie, session complète à 3 joueurs
python3 -m sdsw_server.testclient --players 2       # contre un serveur lancé (--server hôte:port)
```
