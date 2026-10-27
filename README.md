# Cabin Lobby Pets - 0.3.1

Bring everyone's selected cats and dogs into the lobby and beside their assigned chairs in the Cabin, with their own skins.

> 🛟 **Need help or found a bug?** Get support at [support.doodesch.de/lobbypets](https://support.doodesch.de/lobbypets).

The host's pets stay as usual. Pets from other players appear alongside them, update when their owner changes the selection and leave when their owner leaves the lobby.

## Pets in the Cabin

Cabin pets are enabled by default. They spawn on the walkable floor and keep roaming when the Cabin has no water bowl. Use optional [Mod Settings](https://www.nexusmods.com/thecabingame/mods/6) to turn **Pets in the Cabin** on or off. The host controls this setting, and changes take effect next Cabin round. Lobby pets remain enabled.

Without Mod Settings, the mod uses its saved setting. To keep pets in the lobby only, close the game and set `in_cabin = false` in `ue4ss/Mods/CabinLobbyPets/Scripts/settings.lua` on the host.

## Requirements

- [UE4SS for The Cabin Game](https://www.nexusmods.com/thecabingame/mods/4), version `v3.0.1-1164-g5e627997`, on the host and each player whose pets should appear. The [latest experimental UE4SS](https://github.com/UE4SS-RE/RE-UE4SS/releases/tag/experimental-latest) is also available; use the basic archive.
- Cabin Lobby Pets on those same players. Other players can see the pets without this mod.
- Select your pets in the game's pet store.

## Install

1. Close the game and install UE4SS in `the cabin game/the_cabin_game/Binaries/Win64`.
2. Extract this ZIP into the `ue4ss` folder. The result must include `ue4ss/Mods/CabinLobbyPets/Scripts/main.lua`.
3. Start the game and join a lobby with the mod installed on its host.

To remove the mod, close the game and delete `ue4ss/Mods/CabinLobbyPets`.
