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

**Fait** : mod [`en-ligne`](../mods/en-ligne/mod.toml) et serveur [`server/`](../server/README.md), vérifiés avec
deux instances d'Azahar qui jouent ensemble. Ce qui suit explique le choix.

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

## Correctifs

Le mod [`correctifs`](../mods/correctifs/mod.toml) fait partie de toutes les constructions (`always = true`).

**Plantage quand une torpille touche un sous-marin sous l'eau.** Dans Azahar, en mission solo, quelques
instants après qu'une torpille a touché un sous-marin sous l'eau, le jeu se fige et Azahar se ferme. Ce n'est
pas le jeu qui plante : le journal du noyau (`journalctl -k`) montre qu'Azahar est tué par le système faute de
mémoire (« Out of memory: Killed process (azahar) », 5,3 Go de RAM et 4,1 Go d'échange). Le journal d'Azahar
s'arrête avant (il n'écrit sur le disque qu'à chaque erreur).

- Un sous-marin endommagé fuit de l'huile : ses scripts (`surface_sub`, `surface_sub_rival`…, et le joueur au
  replay) appellent `fxOilAdd` toutes les 9 images, et chaque bulle vit 2 secondes.
- `MetaBallSys` (`source/metaball.cpp`) dessine ces bulles seulement quand la caméra est sous l'eau
  (`visibleGroups & 1`), en sprites : le programme 2 de `shaders/metaball.shbin` est un geometry shader qui,
  pour chaque point devant la caméra (entre les plans proche et lointain), fait deux boucles imbriquées :
  `loop i0` dans `main`, qui appelle le sous-programme `draw_strip`, qui contient `loop i1`. Les constantes
  `i0 = i1 = (0, 0, 1, 0)` en font un tour chacune : un carré par bulle.
- Azahar n'accélère jamais un geometry shader sur la carte graphique : il l'exécute avec son JIT de shaders
  (`video_core/shader/shader_jit_x64_compiler.cpp`). `Compile_LOOP` garde le compteur de boucle dans des
  registres de l'hôte (`esi`, `edi`, `r12d`) et ne les sauvegarde que pour une boucle imbriquée dans le même
  bloc de code. La boucle de `draw_strip`, compilée à part, écrase le compteur de la boucle externe et le
  laisse à 0 ; la boucle externe le décrémente (−1) puis teste s'il est nul : elle repart pour environ quatre
  milliards de tours. Chaque tour émet deux triangles, qu'Azahar range dans un tableau avant de les dessiner :
  la mémoire croît de plusieurs centaines de Mo par seconde.

D'où les symptômes : seulement sous l'eau, seulement quand une bulle est devant la caméra (une remontée à la
surface évite le plantage, une nouvelle plongée le déclenche), et plus rien une vingtaine de secondes après le
dernier coup, quand la fuite s'arrête. Le moteur de shaders sans JIT (« Enable Shader JIT » décoché) fait les
boucles correctement.

La correction remplace les deux `LOOP` par des `NOP` (`[[shader]]` dans la recette) : elles ne font qu'un tour
et aucune instruction n'utilise leur compteur (`aL`), donc le shader dessine exactement la même chose.
`tools/shbin.py --check` cherche ce motif (une boucle atteinte par un `CALL` depuis une autre boucle) : seul
`metaball.shbin` l'a. Vérifié dans Azahar avec un mod de test qui fait fuir les sous-marins ennemis en
permanence : sans correctif, la mémoire passe de 1,2 à 3,4 Go en 4 secondes ; avec, elle reste à 1,2 Go et
l'huile s'affiche normalement. Le bug mériterait d'être signalé à Azahar (sauvegarder les registres de boucle
autour de chaque `CALL`, ou les garder dans l'état du shader comme l'interpréteur).

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
