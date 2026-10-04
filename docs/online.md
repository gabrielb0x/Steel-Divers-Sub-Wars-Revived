# Mode en ligne : ce que fait le client, ce que le serveur doit répondre

Reconstitué depuis le code du jeu (EUR v0, révision 31308) : `source/net/connectionInternet.cpp`, le script
`connect.inc` et les bibliothèques NEX 3.7 (`libOnlineCore`, `libRendezVous*`, `libJugem*`, `libMatchmakingClient`,
`libNATTraversalClient`) et Pia (`libpia_inet`), toutes nommées par la table des symboles `romfs:/map`.
C'est la spécification que suit le serveur de [`server/`](../server/README.md), **vérifiée avec le jeu** : deux
instances d'Azahar se connectent, se retrouvent dans un salon et lancent une bataille.

## Vue d'ensemble

| Étape | Qui | Protocole |
|---|---|---|
| 1. adresse du serveur de jeu, jeton | module « friends » de la console → NASC | remplacé par le mod `en-ligne` |
| 2. authentification | serveur d'authentification (UDP) | PRUDP v1 + RMC `TicketGranting` |
| 3. connexion sécurisée | serveur sécurisé (UDP) | PRUDP v1 + Kerberos, RMC `SecureConnection` |
| 4. type de NAT | serveurs « nncs » (UDP 10025/10125) | messages `NATCheckMessage` de 16 octets |
| 5. recherche de partie | serveur sécurisé | `MatchmakeExtension`, `MatchMaking`, `NATTraversal` |
| 6. la bataille | de console à console | Pia (P2P) : le serveur n'y participe pas |

## 1. Connexion : `gameServerLogin` et `JobCTRLogin`

`ConnectionInternet::matchmakerLogin` → `gameServerLogin(ngsFacade, …)` :

1. `nn::friends::CTR::detail::Login` puis attente de l'événement (le module *friends* se connecte aux serveurs de
   Nintendo) ; `GetMyPrincipalId` donne l'identifiant du joueur (gardé par le jeu).
2. `NgsFacade::Login(…, 0x000D7C00, L"fb9537fe", 60000)` : identifiant de serveur NEX, **clé d'accès** `fb9537fe`,
   60 s de délai. La tâche `nn::nex::JobCTRLogin` :
   * `StepFirst` lit `GetGameAuthenticationData` ; si le résultat vaut 1 et le code HTTP 200, elle passe
     directement à `StepGameLogin`, sinon elle demande une authentification (`RequestGameAuthentication`, NASC) ;
   * `StepGameLogin` lit l'adresse et le port du serveur dans ces données (structure de 0x138 octets : +0 résultat,
     +4 code HTTP, +8 adresse sur 32 octets, +0x28 port, +0x30 jeton sur 256 octets, +0x130 heure), le mot de
     passe du compte avec `GetMyPassword` (32 octets), et appelle `RendezVous::Login` avec comme nom d'utilisateur
     le principal ID en décimal et un `AuthenticationInfo` (jeton, version NGS 3, type 0, version serveur 1000).

**Dans Azahar**, `frd:u` est une émulation incomplète : `RequestGameAuthentication` et `GetGameAuthenticationData`
y sont des fonctions vides qui « réussissent » sans rien rendre ni signaler l'événement, et le jeu attend jusqu'au
délai de 60 s. `GetMyFriendKey` (d'où vient le principal ID) rend 0 pour tout le monde. D'où le patch du mod
[`en-ligne`](../mods/en-ligne/mod.toml), qui remplace `GetMyPrincipalId`, `GetMyPassword` et
`GetGameAuthenticationData` : seule fonction appelante pour les deux dernières, `JobCTRLogin`.

## 2. Transport : PRUDP version 1

Les flux de type 10 (RVSecure) utilisent la **version 1** de PRUDP : le constructeur de `PRUDPStream` prend la
version dans une variable globale de NEX initialisée à 1 (octet 0x00399D2E). `PRUDPMessageSelector` accepte aussi
la version 0 et un format de relais (`F5 D0`), que le client n'envoie pas au serveur.

```
EA D0 | version 1 | taille des options | taille des données (u16) | source | destination
      | type + drapeaux (u16 : type sur 4 bits) | session | sous-flux | numéro de séquence (u16)
      | signature (16) | options | données
```

* Types : SYN 0, CONNECT 1, DATA 2, DISCONNECT 3, PING 4. Drapeaux : ACK 0x1, RELIABLE 0x2, NEED_ACK 0x4,
  HAS_SIZE 0x8 (toujours en v1), MULTI_ACK 0x200.
* Options (`PRUDPMessageV1::OptionBuilder`) : SYN et CONNECT portent 0 « fonctions » (u32 : version mineure dans
  l'octet bas ; le client annonce 3), 1 signature de connexion (16 octets), 3 numéro de séquence non fiable
  initial (CONNECT, si non nul), 4 sous-flux maximum (u8) ; DATA porte 2 numéro de fragment (u8, 0 = dernier).
* Signature (`CalcSignatureHelper`) : HMAC-MD5 de clé MD5(clé d'accès) sur les 8 octets d'en-tête de la source au
  numéro de séquence, la clé de session (paquets autres que SYN/CONNECT, sur le serveur sécurisé), la somme des
  octets de la clé d'accès (u32), la signature de connexion **de l'autre côté**, les options et les données
  (chiffrées). Le SYN n'en inclut aucune ; le serveur signe donc avec celle que le client a mise dans son
  CONNECT, et le client avec celle du SYN-ACK du serveur (vérifié sur les paquets du jeu).
* Chiffrement des données (`PacketEncDec`) : RC4, un flux continu par sens, clé de session Kerberos sur le
  serveur sécurisé et **`CD&ML`** sur le serveur d'authentification (trouvé en déchiffrant le premier message du
  jeu : la clé n'apparaît pas telle quelle dans l'exécutable).
* Fiabilité : le premier paquet fiable attendu du serveur porte le numéro 1 (`PacketDispatchQueue`), ceux du client
  commencent à 2 (le CONNECT a le 1). Le jeu acquitte par **ACK groupés** : paquet DATA, drapeau MULTI_ACK sans
  ACK, sous-flux 1, données = u8 sous-flux, u8 nombre n, u16 dernier numéro acquitté (et tous les précédents),
  n × u16. Les PING ont leur propre numérotation et demandent un ACK.

## 3. Authentification et connexion sécurisée

Serveur d'authentification : `prudp:/address=<adresse>;port=<port>;stream=10;sid=1;type=2`
(`JobBackEndServicesLoginWithData::ConnectToAuthenticationService`).

| Appel (protocole 10) | Paramètres | Réponse |
|---|---|---|
| `LoginEx` (2) | String nom (= principal ID), AnyDataHolder `AuthenticationInfo` | résultat, PID, Buffer ticket, `RVConnectionData`, String nom du serveur |
| `RequestTicket` (3) | PID source, PID cible (le serveur sécurisé, 2) | résultat, Buffer ticket |

* Clé de l'utilisateur : MD5 appliqué 65000 + PID mod 1024 fois au mot de passe (`MD5KeyDerivation`).
* Chiffrement Kerberos : RC4(clé) puis HMAC-MD5(clé, chiffré) ajouté à la fin.
* Ticket (déchiffré par le client) : clé de session de 32 octets, PID cible (u32), Buffer ticket interne (opaque
  pour le client, propre au serveur). Le ticket de `LoginEx` sert seulement à vérifier la clé (`ValidateKey`) ;
  la connexion utilise celui de `RequestTicket`.
* `RVConnectionData` (version 1) : URL du serveur sécurisé
  (`prudps:/address=…;port=…;CID=1;PID=2;sid=1;stream=10;type=2`), liste vide, URL vide, heure (DateTime).
* CONNECT au serveur sécurisé : Buffer(ticket interne) + Buffer(Kerberos(clé de session : PID, numéro de connexion,
  valeur de contrôle)) ; le CONNECT-ACK doit contenir Buffer(u32 valeur de contrôle + 1)
  (`JobConnectSecureEndPoint::ProcessConnectResult`).
* `SecureConnection::Register` (11/1) : liste des URL locales → résultat, numéro de connexion (RVCID), URL publique
  telle que le serveur voit le client. `ReplaceURL` (11/7) arrive une fois la détection de NAT finie : Pia met
  dans l'URL privée le port de **sa propre socket** et le type de NAT.

## 4. Détection de NAT (Pia)

`NatTraverser::updateNatServerAddress` déclare à NEX deux serveurs, `nncs1` et `nncs2.app.nintendowifi.net`
(chaînes UTF-16 lues via les pointeurs 0x003B0940/0x003B0944), chacun sur les ports UDP 10025 et 10125. Messages
`NATCheckMessage` de 16 octets gros-boutistes : type, port, adresse, extra ; la réponse renvoie le type et l'adresse
et le port vus par le serveur.

* `NatPropertyDetecter` : type 101 et 102 vers nncs1:10025, 103 vers l'**autre** serveur (autre adresse IP, même
  port). Sans réponse à 101 *et* à 103, la détection échoue. 102 sert au test de filtrage (le serveur de Nintendo
  répondait depuis son autre adresse).
* `NatPortDetecter` : type 101 (port public de la socket de Pia).
* NEX a son propre test (`JobPerformNATCheck`, types 1 à 5).

Notre serveur n'a qu'une adresse : le mod dirige les deux noms vers lui, Pia ne trouve donc pas de second serveur
et n'envoie pas 103 ; le serveur répond 103 en même temps que 101 (Pia ne regarde pas d'où viennent les réponses),
ce qui décrit un NAT dont l'association ne dépend pas de la destination, le cas courant.

## 5. Recherche de partie

`ConnectionInternet::automatchOpen` :

| Appel | Protocole/méthode | Détail |
|---|---|---|
| `AutoMatchmakeWithSearchCriteria_Postpone` | 109/15 | critères (attributs, mode de jeu `1000`, 1 à 8 joueurs, type 1), `MatchmakeSession` « Steel Matcher », message « Steel Diver 2 Auto matchmake » → la session rejointe ou créée |
| `OpenParticipation` / `CloseParticipation` | 109/2 et 109/1 | gid ; l'hôte ouvre le salon, puis le ferme au lancement de la bataille |
| `GetSessionURLs` | 21/41 | gid → URL de l'hôte, pour le rejoindre en P2P |
| `RequestProbeInitiationExt` | 3/3 | URL cibles, URL à sonder : le serveur appelle `InitiateProbe` (3/2) chez chaque cible |
| `ReportNATProperties`, `ReportNATTraversalResult` | 3/5, 3/4 | informatifs |
| `UpdateSessionHostV1` | 21/40 | migration d'hôte |
| `EndParticipation` | 50/1 | quitter le salon |
| `AddToBlackList` / `RemoveFromBlackList` | 109/25, 109/26 | joueurs à ne plus rencontrer |

Si le propriétaire de la session rendue est le joueur, le jeu héberge (Pia `Session::create`) ; sinon il rejoint
l'hôte (`GetSessionURLs` puis `Session::join`).

`MatchmakeSession` (NEX 3.7, `_DDL_MatchmakeSession`) : partie `Gathering` (id, propriétaire, hôte, min/max,
politique, argument, drapeaux, état, description), puis mode de jeu, attributs (liste de u32), participation
ouverte, type de matchmaking, Buffer applicatif (`01 02 03`), nombre de participants, score de progression,
Buffer clé de session, option. Chaque niveau a son en-tête de structure (u8 version, u32 taille).

Attributs (script `connect.inc::joinSession`, native `inetSetAttribute`) :

| # | Signification |
|---|---|
| 0 | continent (`network.continent`) |
| 1 | type de salon (`network.lobbytype`, 1 = combats par niveau) |
| 2 | niveau : rang / 5 (seulement si type de salon = 1), sinon 0 |
| 3 | `sysGetVersionChecksum()` = CRC-32 de la révision du build (`"31308"` → `0xB95D7F2B` en v0) |

Seuls des jeux de la même version se rencontrent. Les identifiants réseau viennent de `bxml/settings.bxml`
(`UniqueId` 3452/3453/3454 selon la région, `NetworkId` commun 3452) : toutes les régions jouent ensemble.

Notifications envoyées par le serveur (protocole 14, méthode 1, `NotificationEvent` : PID source, type, param1,
param2, texte, param3) :

| Type | Quand | Ce qu'en fait le client |
|---|---|---|
| 3001 | un joueur rejoint le salon | `MyNotificationEventHandler` remet un indicateur à 0 |
| 4000 | le propriétaire change (param2) | le jeu note le nouveau propriétaire |
| 109000 | le salon est supprimé (param1) | le jeu le note |
| 110000 | l'hôte change (param1 = gid) | la migration d'hôte de Pia l'attend |

## 6. La bataille

Entièrement en P2P (Pia : sessions, horloge, flux fiables et non fiables, migration d'hôte) entre les sockets de
Pia des consoles. Le serveur n'intervient plus, sauf pour `CloseParticipation` et les départs.
