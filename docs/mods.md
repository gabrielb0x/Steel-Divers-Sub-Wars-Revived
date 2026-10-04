# Mods : ce qui est possible, et comment les distribuer

Objectif : que chaque joueur, avec **sa propre copie** du jeu, puisse appliquer un mod (jeu en ligne sur notre serveur,
60 fps, nouvelles fonctionnalités…) sur 3DS ou sur émulateur.

## Distribuer le mod, jamais le jeu

Un `.cia` modifié contient le jeu entier : le distribuer revient à distribuer le jeu de Nintendo, ce qui est illégal et
contraire à la règle du dépôt (aucune donnée du jeu n'est publiée). On distribue **uniquement le mod** : nos propres
fichiers et des correctifs (patchs) qui ne contiennent que nos modifications. C'est aussi ce que font les mods 3DS
connus.

Format conseillé, qui marche sans toucher au jeu installé :

| Cible | Où mettre le mod | Contenu |
|---|---|---|
| 3DS avec Luma3DS (« game patching » activé) | `luma/titles/00040000000D7E00/` sur la carte SD | `code.ips` ou `code.bps` (patch du code), `romfs/` (fichiers remplacés : scripts `.amx`, `.bxml`…), éventuellement `exheader.bin` |
| Azahar / Citra | `load/mods/00040000000D7E00/` | `exefs/code.ips` (ou `.bps`), `romfs/` |

Le Title ID ci-dessus est celui de la version européenne ; il en faut un dossier par région (`000D7C00` Japon,
`000D7D00` Amérique). Pour ceux qui préfèrent installer un CIA, un petit outil peut fabriquer le CIA modifié **sur la
machine du joueur**, à partir de son propre dump : on publie l'outil et le patch, pas le résultat.

**Version visée** : le patch de code dépend de l'exécutable exact. Les joueurs qui ont joué en ligne ont la mise à
jour installée (la mise à jour 2.0 de juin 2014 remplace tout le contenu du jeu), et Luma applique les patchs au code de
la mise à jour. Les mods doivent donc viser la **dernière mise à jour**, qu'il faut dumper (voir la feuille de route).

## Ce qu'on sait déjà modifier

- **Données** : niveaux, statistiques des sous-marins et de l'équipage, textes, réglages. `make data` les met en XML,
  `tools/bxml.py --to-bxml` les remet en BXML (identiques à l'octet près si on n'y touche pas). Formats dans
  [formats.md](formats.md), dont celui des niveaux.
- **Scripts** : la logique du jeu (modes, sous-marins, interface) est en Pawn ([scripts-pawn.md](scripts-pawn.md)).
  On sait les lire ; pour les modifier il faudra soit un assembleur AMX (modifier le bytecode), soit rendre le
  pseudo-Pawn recompilable avec le compilateur Pawn 3.3. C'est la prochaine brique côté mods.
- **Code C++** : patchs IPS/BPS de `code.bin`, en connaissant les fonctions grâce à la table des symboles du jeu.

## Jeu en ligne sur notre serveur

Comment le jeu trouve son serveur (`source/net/connectionInternet.cpp`, `JobCTRLogin` de la bibliothèque NEX) :

1. `nn::friends::CTR::detail::Login` : le module système *friends* de la console se connecte au serveur d'amis de
   Nintendo, puis fait l'authentification NASC.
2. `nn::friends::CTR::detail::GetGameAuthenticationData` rend le résultat NASC : l'adresse IP et le port du serveur NEX
   du jeu, et un jeton. `JobCTRLogin::StepGameLogin` lit aussi le mot de passe du compte (`GetMyPassword`) et appelle
   `RendezVous::Login` (serveur d'authentification NEX), puis la connexion sécurisée.
3. Le reste (matchmaking, NAT traversal, parties en P2P avec Pia) passe par ce serveur (voir [online.md](online.md)).

Deux façons de rediriger le jeu :

- **Au niveau de la console** (méthode de Pretendo avec Nimbus) : patcher les modules système *friends* et *ssl* pour
  qu'ils parlent à un autre serveur de comptes. Marche pour tous les jeux, mais demande toute une infrastructure de
  comptes (amis, NASC).
- **Au niveau du jeu** (ce qui nous intéresse) : un patch de code qui remplace la connexion au serveur d'amis et le
  résultat NASC par l'adresse de notre serveur et un jeton à nous, avant `RendezVous::Login`. Le mod devient
  autonome : notre serveur n'a qu'à accepter l'identifiant de la console (*principal ID*) et implémenter les
  protocoles NEX du jeu.

Le matchmaking ne réunit que des consoles qui annoncent la même somme de version (CRC-32 du numéro de build,
attribut 3) : un mod qui change le gameplay doit changer cette valeur pour ne pas rencontrer de joueurs sans le mod.

## 60 fps

Ce que fait le moteur aujourd'hui :

- `nnMain` attend au moins **deux VBlank** par image : le jeu est bloqué à 30 fps.
- La simulation avance d'un **pas fixe de 1/30 s** : horloge du monde (`World::update`) et
  `World::getDeltaTimeSeconds()`, qui renvoie la constante 1/30 aux effets (distorsion, flou de vitesse, sillages de
  torpilles, métaballes, fondus, aquarium, générique).
- Les scripts comptent en **images** : minuteurs (`600` = 20 s), animations (`actorPlayAnim` rend une durée en images),
  délais d'appels (`sysCallPublicDelayed`).
- Le **replay** garde les **210 dernières images** (7 s à 30 fps), 80 acteurs par image.

Passer simplement à une image par VBlank ferait tourner tout le jeu deux fois plus vite. Deux voies :

1. **Doubler la fréquence de simulation** : pas de 1/60 dans le C++, et diviser par deux tous les compteurs d'images
   des 123 scripts (et doubler le tampon de replay). Trop de points à corriger à la main, risque de désynchroniser le
   jeu en ligne avec les joueurs à 30 fps.
2. **Simuler à 30 Hz et afficher à 60 Hz** en interpolant entre deux états : le moteur sépare déjà l'état simulé des
   acteurs (`positionPtr`, fonctions `*Sim`) de l'état dessiné (`Actor` +0x4C), copié par `World::postScriptUpdate`.
   Il faudrait dessiner une image intermédiaire en interpolant positions, rotations et caméra. Aucun script à
   toucher, compatible en ligne, mais c'est du code moteur à injecter : plus simple à faire d'abord dans le portage
   PC, puis à reporter en patch 3DS si les performances suivent (la vue stéréo coûte déjà deux rendus par image ; une
   New 3DS sera sans doute nécessaire).

## Menu de debug

Les scripts des modes contiennent encore la console de debug des développeurs (`consoleSystemMenu` dans
`mode_title`, voir [scripts-pawn.md](scripts-pawn.md)) : invincibilité, `godmode`, `killThemAll`, désactivation des
effets, réglages du brouillard et de la 3D, simulation de latence et de pertes de paquets. L'affichage passe par des
fonctions de texte de debug vidées dans la version commerciale ; la réactiver est un bon premier mod à étudier.
