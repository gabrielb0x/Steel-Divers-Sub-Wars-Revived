# Mode en ligne : ce que fait le client

Reconstitué depuis `source/net/connectionInternet.cpp` et le script `connect.inc` (version v0, révision 31308).
C'est la spécification de ce que le serveur de `server/` devra accepter.

## Connexion

`ConnectionInternet::matchmakerLogin` appelle `gameServerLogin(ngsFacade, 0x000D7C00, L"fb9537fe", 60000)` :

| | |
|---|---|
| ID du serveur de jeu NEX | **`0x000D7C00`** |
| Clé d'accès NEX | **`fb9537fe`** (stockée en UTF-16 dans le binaire) |
| Délai d'attente | 60 000 ms |

Séquence :

1. `nn::friends::CTR::detail::Login` (service `frd:u`) : connexion au serveur d'amis puis authentification NASC,
   qui renvoie l'adresse du serveur NEX et un jeton ; le principal ID du joueur est lu avec `GetMyPrincipalId`.
2. `nn::nex::NgsFacade::Login(…, 0xD7C00, "fb9537fe", 60000)` : serveur d'authentification NEX (TicketGranting) puis
   connexion sécurisée (SecureConnection).
3. Création de `MatchmakeExtensionClient` puis `Inet_InitializePiaInet` (Pia sur NEX via `nn::pia::inet::NexFacade`).

## Matchmaking

`initMatchmakeSession` / `setupCriteriaList` / `attemptMatch` :

| Paramètre | Valeur |
|---|---|
| Méthode | `MatchmakeExtension::AutoMatchmake`, message `L"Steel Diver 2 Auto matchmake"` (nom de travail du jeu) |
| Description de la session | `L"Steel Matcher"` |
| Joueurs | min 1, max 8 |
| Mode de jeu (game mode) | `1000` |
| Type de système de matchmaking | `1` |
| Buffer applicatif | octets `01 02 03` |
| Drapeaux de gathering | `0x10` ajouté |
| Attributs | 6 attributs (0 à 5), valeur exacte ou plage dans les critères de recherche |

Attributs fixés par le script `connect.inc::joinSession` (native `inetSetAttribute`) :

| # | Signification |
|---|---|
| 0 | continent (`network.continent`) |
| 1 | type de salon (`network.lobbytype`, 1 = combats par niveau) |
| 2 | niveau : rang / 5 (seulement si type de salon = 1), sinon 0 |
| 3 | `sysGetVersionChecksum()` = CRC-32 de la révision du build (`"31308"` → `0xB95D7F2B` en v0) |

Conséquence : seuls des jeux de la même version se rencontrent. Le portage PC devra annoncer la même somme que les
consoles avec lesquelles il veut jouer.

## Pendant et après une partie

Méthodes RMC appelées par le jeu (en plus du login) :

| Protocole | Méthodes |
|---|---|
| MatchmakeExtension | `AutoMatchmake`, `OpenParticipation`, `CloseParticipation`, `AddToBlackList`, `RemoveFromBlackList` |
| MatchMaking | `GetSessionURLs`, `UpdateSessionHost` (migration d'hôte), `EndParticipation` (via MatchMakingExt) |
| NATTraversal | utilisé par Pia pour la détection de NAT et la traversée |

Les parties elles-mêmes sont en P2P (Pia : sessions, migration d'hôte, horloge de session, flux fiables et non
fiables) ; le serveur n'est pas dans la boucle de jeu. Le serveur Pretendo implémente exactement ces protocoles.
