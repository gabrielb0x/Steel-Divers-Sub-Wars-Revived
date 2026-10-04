# Mods : ce qui est possible, et comment les distribuer

Objectif : que chaque joueur, avec **sa propre copie** du jeu, puisse appliquer un mod (jeu en ligne sur notre serveur,
60 fps, nouvelles fonctionnalités…). Deux cibles : l'émulateur **Azahar** maintenant, et le **portage PC** plus tard,
où les mods seront plus simples encore. La 3DS elle-même n'est pas une cible.

## Distribuer le mod, jamais le jeu

Un `.cia` modifié contient le jeu entier : le distribuer revient à distribuer le jeu de Nintendo, ce qui est illégal et
contraire à la règle du dépôt (aucune donnée du jeu n'est publiée). On distribue **uniquement le mod**, sous forme de
recette ([../mods/README.md](../mods/README.md)) : une liste de changements que `tools/mod.py` applique aux fichiers
du joueur pour produire le dossier qu'Azahar charge :

```
load/mods/00040000000D7E00/romfs/...        fichiers remplacés (textes, niveaux, scripts…)
load/mods/00040000000D7E00/exefs/code.ips   patch du code
```

(chemins vérifiés dans le code d'Azahar, `ncch_container.cpp` : identifiant en hexadécimal majuscule, `code.ips` ou
`code.bps`, `romfs/`, `romfs_ext/`, `exheader.bin`). Le Title ID ci-dessus est celui de la version européenne.

**Installer le jeu dans Azahar** : le CIA de l'eShop contient aussi le manuel électronique, resté chiffré, et Azahar
refuse alors toute l'installation. `tools/azahar.py prepare` fabrique, sur la machine du joueur, un CIA contenant le
jeu seul (et un `.cxi` chargeable directement).

**Version visée** : la version de lancement (v0, Europe), celle du dump. Un patch de code dépend de l'exécutable exact :
les recettes peuvent vérifier les octets d'origine (`expect`).

## Ce qu'on sait déjà modifier

- **Données** : niveaux, statistiques des sous-marins et de l'équipage, textes, réglages ; recettes `[[text]]` et
  `[[bxml]]`. Formats dans [formats.md](formats.md), dont celui des niveaux.
- **Code C++** : recettes `[[code]]` (octets ou assembleur ARM), en connaissant les fonctions grâce à la table des
  symboles du jeu et à la décompilation.
- **Scripts** : la logique du jeu (modes, sous-marins, interface) est en Pawn ([scripts-pawn.md](scripts-pawn.md)).
  On sait les lire ; pour les modifier il faudra un assembleur AMX (modifier le bytecode), puis rendre le pseudo-Pawn
  recompilable avec le compilateur Pawn 3.3. C'est la prochaine brique.

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
  comptes (amis, NASC), et sous émulateur un service *friends* qui la reproduise.
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
   toucher, compatible en ligne, mais c'est du code moteur à injecter : naturel dans le portage PC, plus délicat en
   patch pour Azahar (il faut y loger du code neuf).

## Menu de debug

Les scripts des modes contiennent encore la console de debug des développeurs (`consoleSystemMenu` dans
`mode_title`, voir [scripts-pawn.md](scripts-pawn.md)) : invincibilité, `godmode`, `killThemAll`, désactivation des
effets, réglages du brouillard et de la 3D, simulation de latence et de pertes de paquets, accès au mode de test des
développeurs (`mode_test` : choix du mode, du sous-marin, des missions). Mais ce n'est pas un mod rapide :

- la logique qui ouvre la console et passe d'un menu à l'autre a disparu : aucun script ne remet à zéro le compteur de
  menus (`gConsoleMenuIndex`) ni ne referme la console ; seuls `mode_test` et `mode_controls` ouvrent leurs propres
  menus ;
- l'affichage aussi : `gfxPrintStringf` écrit toujours dans un tampon de texte de 50 colonnes
  (`System::getDebugBuffer`, 0x800 caractères), mais plus aucun code ne le dessine (`DebugFX::draw` ne trace que des
  lignes de debug).

Il faudrait réécrire ces deux morceaux : naturel dans le portage PC (une surcouche de debug), possible plus tard dans
Azahar avec des patchs de scripts et de code.
