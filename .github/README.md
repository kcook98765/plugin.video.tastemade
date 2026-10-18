# Tastemade for Kodi — private development repository

Unofficial experimental add-on targeting **Kodi 20/Nexus and 21/Omega APIs**.
The retained add-on ID and userdata namespace are `plugin.video.tastemade.workstation`.
Source version is **0.1.0**; manual-test ZIP versions are separate identifiers.
Not affiliated with or endorsed by Tastemade.

## Browsing and playback

- The catalogue offers direct **VOD** and **Live TV** entries; playlists are discovered dynamically.
- Season grouping scans at most **300 episodes**, with an **All episodes** fallback;
  playlist and episode pages contain **30 items**, with Previous/Next navigation.
- Catalogue artwork, descriptions and rich Kodi Information metadata are supported.
  Local icon/fanart are original static artwork: no official logos or images,
  no runtime Pillow dependency, and no genuine screenshot gallery yet.
- VOD's HLS master/external-audio linkage is fixed. Playback supports entitled,
  unencrypted direct HTTPS HLS; DRM, purchases and geographic bypass are unsupported.
- Live TV is optional and **off by default**, using direct InputStream Adaptive (ISA).
  Use **ISA 20.3.18+ on Nexus** or **21.4.3+ on Omega**, matching Kodi's major branch.
  **Install/Enable** prompts require user consent; older ISA versions need a manual update.
  Browsing, accounts and VOD do not require ISA.

## Account and privacy

Use an eligible existing Tastemade account in **Settings → Account**, save, then
choose **Verify login**. Defaults are blank; password masking is not encryption.
Session tokens/settings belong in the private Kodi profile, protected by file
permissions, **not encrypted storage**. Never commit accounts, settings or caches.
Python diagnostics are sanitized; credentials, tokens and playback URLs are excluded.
Native Kodi/ISA logging of media/session URLs is accepted; keep raw logs private.
Account credentials, reusable tokens and cookies are not forwarded to media hosts.

## Private packaging

Preserve these **sixteen runtime paths** inside the ZIP's top-level directory
`plugin.video.tastemade.workstation/`:

```text
LICENSE.txt
README.md
addon.xml
default.py
resources/settings.xml
resources/language/resource.language.en_gb/strings.po
resources/lib/auth.py
resources/lib/catalog_metadata.py
resources/lib/catalogue.py
resources/lib/diagnostics.py
resources/lib/live_playback.py
resources/lib/plugin.py
resources/lib/service.py
resources/icon.png
resources/fanart.jpg
resources/ARTWORK-NOTICE.txt
```

Install through Kodi **Settings → Add-ons → Install from zip file**.
`tools/build_addon_art.py` is repository-only tooling using existing Pillow at build
time. Exclude it, tests, Git data, ZIPs, accounts and caches from runtime packages.

## Verification

Recorded offline result: **235 tests passed**, using synthetic data and mocked Kodi.
Static validation and bounded native checks are separate, build-specific evidence.
The user reported that Shield presentation “looks good”; this is not exact-build
automated full QA or proof of complete playback/live-session reliability.
Run tests from the repository root. For static validation, use a source-only
export whose directory matches the add-on ID, not the whole repository with
tests/Git metadata; replace placeholders with local directories.

```sh
python3 -B -m unittest discover -s tests -v
python -m kodi_agent_toolkit.cli validate <ADDON_DIRECTORY> --branch nexus --cache <CACHE_DIRECTORY>
```

`PROVENANCE.json` records the **historical generation-9 import**, not current source.
This repository is **not a registered Kodi Lab development source**.
The existing **MIT license in `LICENSE.txt`** is preserved. Tastemade content and
trademarks are not licensed or redistributed here; no official images are included.
