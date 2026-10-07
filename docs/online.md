# Mode en ligne : ce que fait le client, ce que le serveur doit répondre

Reconstitué depuis le code du jeu (EUR v0, révision 31308) : `source/net/connectionInternet.cpp`, le script
`connect.inc` et les bibliothèques NEX 3.7 (`libOnlineCore`, `libRendezVous*`, `libJugem*`, `libMatchmakingClient`,
`libNATTraversalClient`) et Pia (`libpia_inet`), toutes nommées par la table des symboles `romfs:/map`.
C'est la spécification que suit le serveur de [`server/`](../server/README.md), **vérifiée avec le jeu** : deux
instances d'Azahar se connectent, se retrouvent dans un salon et lancent une bataille.

## Vue d'ensemble

*Avancement estimé : 100 %.*

| Étape | Qui | Protocole |
|---|---|---|
| 1. adresse du serveur de jeu, jeton | module « friends » de la console → NASC | remplacé par le mod `en-ligne` |
| 2. authentification | serveur d'authentification (UDP) | PRUDP v1 + RMC `TicketGranting` |
| 3. connexion sécurisée | serveur sécurisé (UDP) | PRUDP v1 + Kerberos, RMC `SecureConnection` |
| 4. type de NAT | serveurs « nncs » (UDP 10025/10125) | messages `NATCheckMessage` de 16 octets |
| 5. recherche de partie | serveur sécurisé | `MatchmakeExtension`, `MatchMaking`, `NATTraversal` |
| 6. la bataille | de console à console | Pia (P2P) : le serveur n'y participe pas |
| 7. joueurs éloignés | serveur, box | adresse publique, redirections UPnP, joueurs du réseau du serveur |
| 8. réglages du serveur | serveur → jeu | notifications à nous, variables de script (mod `en-ligne`) |

## 1. Connexion : `gameServerLogin` et `JobCTRLogin`

*Avancement estimé : 100 %.*

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

*Avancement estimé : 100 %.*

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

*Avancement estimé : 100 %.*

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

*Avancement estimé : 100 %.*

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

*Avancement estimé : 95 % — reste à l'éprouver avec beaucoup de joueurs à la fois.*

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

## 6. Le salon et la bataille

*Avancement estimé : 85 % — reste à éprouver la migration d'hôte et les départs en cours de partie.*

Entièrement en P2P (Pia : sessions, horloge, flux fiables et non fiables, migration d'hôte) entre les sockets de
Pia des consoles. Le serveur n'intervient plus, sauf pour `CloseParticipation` et les départs.

Ce que décide le jeu lui-même (scripts `mode_lobby` et `mode_periscope`) :

* **Compte à rebours** : 120 s (`0x1D4C0` ms dans `mode_lobby`), lancé seulement quand chaque équipe a au moins
  un joueur (`checkCountdownStart`, `g_504c = 1`) ; à 5 s de la fin l'hôte ferme le salon
  (`doNetSetParticipation(0)` → `CloseParticipation`). Seul, on attend indéfiniment.
* **Bots** : au début de la bataille, le premier joueur de chaque équipe crée `4 − joueurs de l'équipe`
  sous-marins pilotés par l'ordinateur (`@setNpc`, acteurs `surface_sub_npc_blue/red`, au plus 3). Une équipe
  sans joueur n'a pas de bots. Le mode de debug `player.debugmulti` (`gDebugSingleInMulti`, jamais activé)
  les supprime.
* **Invincibilité** : le drapeau `player.muteki` (mode test des développeurs) annule les dégâts reçus
  (`pscope_player`), le décompte des torpilles et la perte d'air (`periscope_move`). Les dégâts sont appliqués
  par la console qui les subit : la triche marche aussi en ligne, d'où l'option `cheats` du serveur.

## 7. Joueurs éloignés : adresses publiques et privées

*Avancement estimé : 85 % — validé en simulation et sur le réseau local, pas encore entre deux vraies maisons ; pas de relais pour les NAT stricts.*

Pour rejoindre l'hôte, Pia reçoit ses URL (`GetSessionURLs`, une ou deux, sinon erreur :
`NexFacade::ConvertNexStationURLToStationConnectionInfo`), classe l'une comme publique (bit 2 du paramètre `type` :
`NexFacade::IsPublic` ; bit 1 = derrière un NAT) et l'autre comme privée, puis
(`NexConnectStationJob::StartupImpl`) :

* si l'adresse IP publique de l'hôte est **la sienne** (même réseau derrière la même box), il vise l'adresse
  **privée** ;
* sinon il vise l'adresse **publique**, et la traversée de NAT de NEX (`RequestProbeInitiationExt`, `InitiateProbe`)
  fait sonder chacun par l'autre.

Sa propre adresse publique vient de l'URL que `SecureConnection::Register` lui a rendue
(`JobBackEndServicesLogin::CompleteLogin` l'ajoute à ses URL locales ; `NatTraverser::updateLocalStationInfo` la
reprend). Une console sur la machine du serveur s'y connecte par `127.0.0.1` : le serveur la verrait sous cette
adresse et la donnerait aux autres, injoignable. Quand le serveur a une adresse Internet, il présente donc les
consoles de son propre réseau (boucle locale, ou réseau local derrière la même box) sous **son adresse publique**,
partout où le jeu l'apprend : réponse de `Register`, réponses de la détection de NAT, URL publique transmise aux
autres (`server/sdsw_server/internet.py`).

La socket de Pia prend un port au hasard entre 49152 et 65534 (`NatDetecter::bindRandomPort`,
`GetDifferentPortNumber`, différent de celui de NEX). Le serveur l'apprend par `ReplaceURL` et le fait rediriger
par la box (UPnP) vers la console à domicile tant qu'elle est connectée. C'est nécessaire avec les box sous Linux
(simulation : deux NAT `nftables` « masquerade » dans des espaces de noms réseau, le serveur et l'hôte derrière
l'un, un ami derrière l'autre) : les premières sondes de l'ami arrivent sur la box de l'hôte avant que l'hôte ait
écrit à l'ami, y créent une entrée de suivi de connexion, et la réponse de l'hôte sort alors par un autre port, que
le NAT de l'ami rejette. Avec la redirection, l'échange passe dans les deux sens, que l'hôte de la partie soit
l'ami ou le joueur à domicile ; sans elle, dans aucun.

Les noms sont résolus : `nn::nex::InetAddress::SetAddress` appelle `GetHostByName` quand l'adresse n'est pas
numérique (drapeau `0x00399D1F`, à 1 dans l'exécutable), et Pia résout les noms des serveurs de détection de NAT.
Le mod accepte donc un nom (DNS dynamique) à la place d'une IP.

## 8. Serveur → jeu : les variables du mod

*Avancement estimé : 100 %.*

Le serveur n'a aucun moyen d'agir sur une bataille, qui se joue de console à console. Pour régler les
parties contre des bots (et plus tard d'autres choses), le mod `en-ligne` réécrit
`MyNotificationEventHandler::ProcessNotificationEvent` (0x00185264, 568 octets dont l'essentiel écrivait des
journaux retirés de la version finale) : il garde les trois notifications que le jeu retenait (3001, 4xxx,
109xxx) et en ajoute deux, inconnues du jeu d'origine qui les ignore :

| Type | Texte | param1 | Effet dans le jeu |
|---|---|---|---|
| 999001 | nom | valeur | `amxSysSetGlobal(nom, valeur)` : une variable entière des scripts |
| 999002 | `nom=valeur` | — | `amxSysSetGlobalArray(nom, 96 cellules)` : une chaîne, comme `sysSetGlobalString` |

Le texte d'une notification arrive en UTF-16 (`nn::nex::String`, tampon en +4) ; le patch le convertit en
UTF-8 avec la fonction du jeu (`convertUTF16toUTF8`). Seuls les noms qui commencent par `server.` sont
acceptés : un serveur ne peut toucher ni à la sauvegarde (`save.*`) ni aux variables du jeu. NEX distribue
les notifications sur le fil principal, pendant `Network::dispatch()`, là où tournent les scripts.

Variables utilisées (`server/sdsw_server/matchmaking.py` et `realm.py`, `mods/en-ligne/*.pasm`) :

| Variable | Sens |
|---|---|
| `server.bots` | 1 : la partie se joue contre des bots (remis à 0 à chaque nouveau salon) |
| `server.bots.mine`, `server.bots.other` | tailles de l'équipe des joueurs et de l'autre |
| `server.bots.stage` | carte (`player.stage`, 10 à 19), 0 : au hasard |
| `server.bots.level` | 1 normal, 2 difficile (sans valeur), 3 expert : réflexes et précision de tous les bots des parties en ligne |
| `server.bots.countdown`, `server.bots.duration` | compte à rebours (ms) et durée de la bataille (s) |
| `server.bots.name<k>`, `sub<k>`, `lv<k>` | le bot k (1 à 7) : nom, sous-marin (1 à 23), niveau affiché |
| `server.anticheat` | 1 : les jeux de cette partie se surveillent eux-mêmes (envoyé à chaque recherche ; 0 avec `cheats = "autorises"` et entre tricheurs) |

Dans l'autre sens, le jeu n'a que sa recherche de partie pour parler au serveur : le mod met dans
l'attribut 4 des critères (`inetSetAttribute(4, …)`, à côté de la somme de version en 3) le rapport de
l'anti-triche, `0x100` (un jeu qui se surveille) | ce qu'il a vu à son dernier renvoi (bits 0-7 : 1 dégâts
annulés, 2 torpilles infinies, 4 tirs trop rapprochés, 8 vitesse impossible) | le numéro de ce renvoi
(bits 16-30). Le jeu garde son dernier renvoi dans la sauvegarde (`save.sdsw.cheat`, `save.sdsw.kick`) et le
répète à chaque recherche ; le serveur ne traite qu'une fois chaque numéro (`exclusions.json`). Les
attributs 4 et 5 ne servent pas à apparier les joueurs.

## 9. La mise à jour v5200

*Avancement estimé : 70 % — connexion, recherche de partie et salon vérifiés avec la v5200 dans Azahar ; restent les
bots et l'anti-triche du mod pour elle.*

La mise à jour ([mise-a-jour.md](mise-a-jour.md)) garde le même identifiant de serveur NEX (`0x000D7C00`), la même
clé d'accès (`fb9537fe`) et les mêmes bibliothèques NEX et Pia, à de nouvelles adresses : le même serveur la sert.
Différences relevées pour le mod `en-ligne` :

- les fonctions de `frd` et les étapes de `JobCTRLogin` sont identiques (`GetMyPrincipalId` `0x00222740`,
  `GetMyPassword` `0x002C9224`, `GetGameAuthenticationData` `0x002226CC`) ;
- **le Pia de la v5200 résout les noms des serveurs de NAT en ASCII** (`NatTraverser::updateNatServerAddress`, table
  `0x003D8018`), celui de la v0 en UTF-16 (`0x003B0940`) ; la table de NEX reste en UTF-16 (`0x003C13E4`) ;
- `MyNotificationEventHandler::ProcessNotificationEvent` (`0x0018A7B8`) est la même, sauf que le nouveau
  propriétaire (notification 4xxx) va en `+0x1C` de sa structure (`0x003B5668`), contre `+0x18` en v0 ;
- la somme de version de la recherche de partie (attribut 3, `sysGetVersionChecksum`) vaut **868960903** en v5200
  (0xB95D7F2B en v0) : le serveur compare les attributs 0 à 3, donc les joueurs des deux versions ne se retrouvent
  pas dans la même partie, et c'est voulu (cartes, sous-marins et scripts diffèrent) ;
- le menu multijoueur de la v5200 n'a plus l'état inutilisé où le mod ouvrait le dialogue du serveur : il s'ouvre
  dans l'état Dialog du jeu, et sa fermeture mène au menu Internet (accroches `0xA4B4` et `0x603C`).

