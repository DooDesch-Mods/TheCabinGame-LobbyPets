# Publishing

Release only after the exact runtime payload has genuine evidence for all six checks in acceptance.json. accepted remains false while native or host/peer acceptance is open. Candidate builds do not require acceptance and do not authorize publication.

Use the manual release workflow with publish_nexus enabled for the combined GitHub/Nexus release. Do not create the GitHub release manually first. The workflow validates acceptance, creates or verifies the canonical tag and ZIP/checksum, captures the latest Main File requirements, uploads through the pinned Nexus action, then verifies the acknowledged version and file-to-file ranges before dispatching one Discord announcement.

The existing organization secrets NEXUSMODS_API_KEY and DISCORD_RELEASE_WEBHOOK stay in GitHub Secrets. Configure NEXUS_MOD_ID and NEXUS_FILE_GROUP_ID for this exact mod and its existing Main File. NEXUS_VORTEX_READY is true only after an actual manager download and deployment pass.

The release helper supports published and unpublished parents. It preserves the existing UE4SS minimum file version 45363444580354 through Latest and retains dist/nexus-release.json as a CI artifact. It verifies the configured mod, file group, canonical version and exact requirements readback. The receipt distinguishes local archive verification from an unconfirmed remote archive hash.

After failure or timeout, inspect retained receipts and the actual GitHub/Nexus state before retrying. Existing Nexus versions and changed tags or archives block automatic overwrite. Do not dispatch Discord again for an already announced release.

No game files, loader binaries, diagnostics, user settings or extracted original assets belong in the release ZIP.
