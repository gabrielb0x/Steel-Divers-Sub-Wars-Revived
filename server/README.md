# Serveur en ligne

Serveur de remplacement pour le mode en ligne de Steel Diver: Sub Wars : connexion des joueurs, recherche de
partie (matchmaking) et aide à la connexion directe entre consoles (NAT traversal). Les parties elles-mêmes se
jouent de console à console (Pia, en P2P) : le serveur ne voit passer que la tenue des salons.

Écrit en Python (3.11 ou plus récent), **sans aucune dépendance** : la bibliothèque standard suffit. Tout ce qu'il
implémente vient de la rétro-ingénierie du jeu (EUR v0) ; le détail est dans [../docs/online.md](../docs/online.md).

**Vérifié avec le vrai jeu** : deux instances d'Azahar équipées du mod [`en-ligne`](../mods/en-ligne/mod.toml)
se connectent, se retrouvent dans le même salon et lancent une bataille ensemble.

## Lancer le serveur

```sh
cd server
python3 -m sdsw_server            # les deux royaumes de serveur.toml + la détection de NAT
python3 -m sdsw_server --realm emulateur -v      # un seul royaume, journal détaillé (-vv : paquets)
```

## Deux royaumes : émulateur et PC

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

Chaque royaume a deux options de partie dans `serveur.toml` :

* **`max_players`** (2 à 8) : nombre de joueurs humains par partie. Les bots existent déjà dans le jeu : la
  console hôte complète chaque équipe à 4 sous-marins avec des sous-marins pilotés par l'ordinateur
  (`mode_periscope` › `@setNpc`, 4 − joueurs de l'équipe). Limiter les humains donne donc plus de bots :
  `max_players = 2` fait toujours du un contre un, avec 3 bots de chaque côté. Le serveur ne peut pas jouer
  lui-même un bot (la bataille se joue entre les consoles), et le jeu exige au moins un joueur dans chaque
  équipe pour lancer le compte à rebours : il faut être au moins deux.
* **`cheats`** : que faire des joueurs dont le mod contient [la triche](../mods/triche/mod.toml) ou des
  [caractéristiques de sous-marins modifiées](../mods/specs/mod.toml) (leur jeton le déclare : drapeaux
  `triche` et `specs`) : `"separes"` (par défaut : ils ne rencontrent que d'autres tricheurs), `"autorises"`
  (ils jouent avec tout le monde) ou `"refuses"` (connexion refusée). Le mod [`premium`](../mods/premium/mod.toml)
  (drapeau `premium`) n'est pas de la triche : il donne ce que les joueurs premium avaient. La triche elle-même
  est dans le jeu, pas dans le serveur ; un jeu modifié autrement peut toujours mentir, comme dans tout jeu
  en P2P. Pour un serveur où tout le monde triche, mettre `cheats = "autorises"`.

## Héberger un serveur public

1. Dans `serveur.toml`, mettre dans `public_address` l'adresse IP publique (ou le nom) de la machine : c'est
   l'adresse du serveur sécurisé envoyée aux joueurs après l'authentification.
2. Ouvrir (ou rediriger sur la box) en **UDP** : 61000-61001, 61010-61011 si le royaume PC sert, 10025 et 10125.
3. Les joueurs construisent le mod avec cette adresse :
   `tools/mod.py build en-ligne --set server=<adresse> --install`.

## Comptes

Pas d'inscription : sur 3DS, le mot de passe venait des serveurs de comptes de Nintendo. Le mod donne à chaque
joueur un identifiant (principal ID) et un mot de passe aléatoires, créés quand il construit le mod ; le jeton
d'authentification contient la clé Kerberos dérivée du mot de passe. Le serveur enregistre l'identifiant à sa
première connexion et exige ensuite la même clé (`data/<royaume>/accounts.sqlite3`).

Aucune donnée de jeu n'est stockée : le jeu n'utilise pas de classements ni de stockage côté serveur.

## Organisation du code

| Fichier | Rôle |
|---|---|
| `sdsw_server/prudp.py` | transport PRUDP v1 : poignée de main, signatures HMAC, RC4, fiabilité, fragments |
| `sdsw_server/rmc.py` | appels de méthodes (RMC), dans les deux sens |
| `sdsw_server/streams.py`, `ddl.py` | sérialisation NEX et structures du jeu (MatchmakeSession, critères…) |
| `sdsw_server/crypto.py` | RC4, chiffrement Kerberos, dérivation de clé |
| `sdsw_server/realm.py` | serveur d'authentification (TicketGranting) et serveur sécurisé (SecureConnection, NATTraversal, MatchMaking, MatchmakeExtension) |
| `sdsw_server/matchmaking.py` | salons, notifications |
| `sdsw_server/natcheck.py` | détection de NAT de Pia (serveurs « nncs ») |
| `sdsw_server/accounts.py` | comptes |
| `sdsw_server/testclient.py` | client qui se comporte comme le jeu, pour tester sans console |

## Tests

```sh
cd server
python3 -m unittest discover -s tests -t . -v      # formats, cryptographie, session complète à 3 joueurs
python3 -m sdsw_server.testclient --players 2       # contre un serveur lancé (--server hôte:port)
```
