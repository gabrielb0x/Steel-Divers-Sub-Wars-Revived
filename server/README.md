# Serveur online

Pas encore commencé. Voir le volet 3 de [../docs/roadmap.md](../docs/roadmap.md).

Ce qu'on sait déjà :

- le jeu utilise NEX (authentification, matchmaking, NAT traversal) et joue les parties en P2P via Pia ;
- [Pretendo](https://github.com/PretendoNetwork/steel-diver-sub-wars) a un serveur fonctionnel (Go, AGPL-3.0) :
  NEX 3.7.0, clé d'accès `fb9537fe`, protocoles TicketGranting, SecureConnection, NATTraversal, MatchMaking,
  MatchMakingExt, MatchmakeExtension.

Ce que le client attend (ID de serveur `0x000D7C00`, clé `fb9537fe`, attributs de matchmaking, méthodes RMC) :
[../docs/online.md](../docs/online.md).

Objectif : un serveur autonome, hébergeable par n'importe qui, utilisable par le portage PC et par de vraies 3DS.
