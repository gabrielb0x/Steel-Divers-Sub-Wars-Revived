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
  (avec leurs messages) sont toujours là, ce qui documente beaucoup de code.

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
déduit automatiquement de l'implémentation C++ (`tools/native_types.py`).

## Outils

`make scripts` (après `make export`) produit, dans `decomp/scripts/` (non versionné) :

- `asm/*.asm` : désassemblage avec labels, natives et leur implémentation C++, chaînes littérales ;
- `*.p` : **pseudo-Pawn décompilé** (`tools/amxdec.py`).

Le décompilateur reconstruit les expressions, les variables locales et les tableaux (y compris 2D), les appels de
natives typés, les opérateurs flottants de `float.inc`, les conditions `&&`/`||`, les ternaires, et les structures
`if`/`else`, `while`, `for`, `switch`, `break`/`continue`. Sur les 6 037 fonctions, il reste 132 `goto`, presque tous
dans `sale_script`.

Exemple (`hud.amx`) :

```pawn
switch (arg0) {
    case 4:
        sysGetString(local_180, "sub_display_hit", 96);
    case 6:
        sysGetString(local_180, "sub_display_homing_hit", 96);
    ...
```

Limites : les noms des variables locales, des globales et des fonctions sans log restent synthétiques
(`local_14`, `g_01c8`, `func_02c0`), et les natives n'ont pas encore de prototypes Pawn nommés.
