# Les scripts Pawn du jeu

Une grande partie de la logique de Steel Diver: Sub Wars n'est pas en C++ mais dans **123 scripts Pawn compilés**
(`romfs:/amx/*.amx`). Le moteur C++ les exécute avec la machine virtuelle AMX de CompuPhase (Pawn 3.3, format de
fichier 10) et leur fournit 647 fonctions natives.

## Organisation

- **Modes** : `nnMain` charge un script `mode_*` (20 au total), le fait tourner, puis passe au suivant
  (`decomp/src/main.cpp`). Chaque mode boucle une fois par frame et rend la main au moteur avec `sleep 0;`.

  ```
  mode_title  mode_select  mode_lobby  mode_internet_menu  mode_local_menu  mode_multi_menu
  mode_periscope  mode_peri_result  mode_mission_select  mode_shop  mode_sale  mode_customize
  mode_battle_record  mode_options  mode_settings  mode_controls  mode_staff  mode_giles  mode_test  mode_warning
  ```

- **Acteurs** : les objets du monde sont scriptés (`surface_sub`, `surface_torpedo_homing`, `surface_mine`,
  `surface_ship_boss`, `surface_fortress`…), ainsi que les caméras (`camera_*`) et l'interface (`hud`, `pause`, `sonar`,
  `morse`…). Fonctions publiques appelées par le moteur : `@actorSync` (tous les scripts), `@eventCollide`,
  `@torpedoHit`, `@setPlayersPerTeam`, `@saveAll`…
- **Includes partagés** : les messages de log `[fichier::fonction]` restés dans les scripts redonnent les noms des
  fonctions et les fichiers `.inc` d'origine : `actor.inc`, `button.inc`, `cards.inc`, `connect.inc`, `controls.inc`,
  `game_state.inc`, `lobby.inc`, `medal.inc`, `morse.inc`, `options.inc`, `overlay.inc`, `points.inc`, `rest.inc`,
  `save.inc`, `stageutil.inc`, `stats.inc`, `sub_customize.inc`, `surface_ship.inc`, `system.inc`, `torpedo.inc`…
- **Debug retiré** : les fonctions d'affichage de debug sont vides dans la version commerciale, mais leurs appels
  (avec leurs messages) sont toujours là, ce qui documente beaucoup de code. Le décompilateur les nomme
  `debugPrint` (ou `stub` quand elles ne reçoivent pas de message).
- **États Pawn** : 23 scripts (les modes et les unités du mode surface) utilisent les automates de Pawn
  (`fonction() <état>`, `state nom;`). Le compilateur place devant la première fonction un aiguillage
  (`load.pri <variable d'état>; switch`) vers l'implémentation de l'état courant ; le décompilateur l'affiche
  comme dans le source (`func_0010(arg0, arg1) <state2>`, `state state3;`), avec des noms d'états numérotés.
- **UID des scripts** : un script prend un identifiant avec `sysSetUID()` ; les autres l'appellent par lui
  (`sysCallPublic(UID_HUD, "@setBossLifeMeter", …)`). 10000 est le mode en cours, 10010 le HUD, 11030 `game_state`,
  10100 le joueur… (énumération `UID` de `decomp/pawn/natives.inc`). En dessous de 1000, l'UID est un numéro d'acteur.
- **Console de debug** : `mode_title` (et les autres modes) contiennent encore un menu de debug complet
  (`consoleSystemMenu` : invincibilité `player.muteki`, `player.godmode`, `killThemAll`, `life100%`, désactivation
  des effets, brouillard, latence et pertes de paquets simulées pour le réseau…), piloté par l'engine global
  `system.consolemode`. Piste pour un futur mod.

## Natives (fonctions C++ appelées par les scripts)

Les tables d'enregistrement (`AMX_NATIVE_INFO`, déclarées *packed* donc parfois non alignées) sont retrouvées en
suivant les appels à `amx_Register` :

| Module | Natives | | Module | Natives |
|---|---|---|---|---|
| `amxsys` (système, globales, sauvegarde) | 161 | | `amxxml` | 26 |
| `amxactor` (acteurs) | 148 | | `amxworld` (monde) | 25 |
| `amxnet` (réseau) | 59 | | `float` | 22 |
| `amxeffects` | 56 | | `amxstring`, `amxcore`, `amxcons` | 19, 17, 15 |
| `amxgfx` (caméras, rendu) | 48 | | `amxvector` | 17 |
| `amxsound` | 30 | | `amxbb`, `amxdynamics` | 2, 2 |

Les scripts en utilisent 466. Le type de chaque paramètre (chaîne en entrée/sortie, tableau, Float, entier) est
déduit automatiquement de l'implémentation C++ (`tools/native_types.py`), et **`decomp/pawn/natives.inc`** donne les
prototypes Pawn écrits à la main des ~340 natives les plus utilisées (noms des paramètres, `Float:`, références,
fonctions variadiques), plus les énumérations `UID` et `BUTTON`. Conventions du jeu : l'acteur visé est le dernier
paramètre des natives `actor*` (0 = l'acteur du script appelant), les vecteurs sont des `Float:v[3]`.

## Outils

`make scripts` (après `make export`) produit, dans `decomp/scripts/` (non versionné) :

- `asm/*.asm` : désassemblage avec labels, natives et leur implémentation C++, chaînes littérales ;
- `*.p` : **pseudo-Pawn décompilé** (`tools/amxdec.py`).

Le décompilateur reconstruit les expressions, les variables locales et les tableaux (y compris 2D), les appels de
natives typés, les opérateurs flottants de `float.inc`, les conditions `&&`/`||`, les ternaires, les structures
`if`/`else`, `while`, `for`, `switch`, `break`/`continue`, et les états Pawn. Il reste environ 130 `goto`, presque tous
dans `sale_script`.

Il analyse tous les scripts ensemble, en plusieurs passes :

1. **Types des paramètres** : chaque fonction de script apprend comment ses paramètres sont utilisés (passés à une
   native qui attend une chaîne, un tableau, un `Float`, écrits par référence…), de proche en proche à travers les
   appels. Les appels s'affichent alors avec des chaînes, des flottants et des noms de globales au lieu d'adresses
   (`consoleGlobalFloat("fog mindepth", "fog.near", 10.0, -1000000.0, 1000000.0, 0)` au lieu de
   `func_2f28(10000, "fog.near", 0x41200000, -0x368bdc00, 0x49742400, 0)`), et les déclarations sont typées
   (`setControlAction(const control[], action, bool:replace)`).
2. **Correspondance entre scripts** (`tools/amxsym.py`) : les 6 037 fonctions viennent des mêmes `.inc` compilés dans
   plusieurs scripts. Une empreinte du code normalisé (natives par nom, chaînes par contenu, globales renumérotées,
   fonctions appelées par leur propre empreinte) regroupe les copies : 4 500 fonctions appartiennent à ~600 groupes.
   Un nom donné une fois s'applique à toutes les copies, et les globales qu'elles utilisent à la même place sont
   reliées entre scripts.
3. **Noms** : noms d'origine (logs `[fichier.inc::fonction]` ou `[fonction]`), puis **`decomp/pawn/symbols.txt`**
   (noms et paramètres donnés à la main, versionnés, marqués `[named by hand]` dans la sortie), fichier `.inc` déduit
   des voisines pour les fonctions sans log, globales initialisées avec un nom appelées d'après lui (`g_btn_ok`).

Exemple (`mode_title.amx`, `controls.inc`) :

```pawn
// 0x0a8c  controls.inc  [named by hand]
setControlSet(set)
{
    ...
    sysSetGlobal("controls.controlSet", set);
    sysGetGlobalString("mode.current", local_180);
    sysCallPublic(UID_CAMERA, "@resetControlData");
    switch (set) {
        case 0:
            setStandardControls(local_184);
            setActionForInput(BUTTON_X, 1, 1);
    ...
```

Pour nommer une fonction : lire son code dans `decomp/scripts/*.p`, ajouter une ligne
`<script>:<adresse> nom(paramètres)` à `decomp/pawn/symbols.txt`, relancer `make scripts`.

Limites : les variables locales et la plupart des globales restent synthétiques (`local_14`, `g_01c8`), comme les
noms d'états ; ~1 500 groupes de fonctions n'ont pas encore de nom.
