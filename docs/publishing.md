# Publishing Lobby Pets

The first Nexus page and Main File are created manually from the prepared upload folder. Later updates use the same GitHub Actions flow as Palvolve and ChairMarker.

| Repository variable | Value |
| --- | --- |
| NEXUS_FILE_GROUP_ID | API File ID from this mod's Main File > Advanced |
| NEXUS_MOD_ID | Unique Mod ID from the same panel |
| NEXUS_VORTEX_READY | true only after this mod's actual manager download and installation have passed |

NEXUSMODS_API_KEY and DISCORD_RELEASE_WEBHOOK use the existing organization secrets. Keep their values in GitHub Secrets.

Check and build verifies Lua syntax, release routing, reproducible packaging and installation boundaries on Linux and Windows. Publish vMAJOR.MINOR.PATCH only after that exact commit passes and both CI package hashes match the local archive. Upload the ZIP and SHA256SUMS.txt with the release.

The release verification checks uploaded files against the tag and checksum. Missing first-upload Nexus configuration is reported as a skipped upload. An explicitly requested upload with missing configuration fails. After an unclear result, inspect Nexus before retrying.

Release announcements target Discord channel 1534536549642014810 and use docs/thumbnail.png. Manual workflow checks do not send a message unless announce is selected. Saved-message acknowledgement is retained as an artifact.
