# Contributing

The [README](README.md) is the installation and usage guide. This document covers
local source checks and preparation of standalone add-on packages.

## Add-on identity and compatibility

- The Kodi add-on ID is **`plugin.video.tastemade`**. Keep `addon.xml`, the settings
  section, translation header and package root consistent with it.
- The source manifest currently declares version **0.1.0**. A version in source
  is not evidence that a release has been published.
- Target Kodi 20/Nexus and 21/Omega APIs. The optional InputStream Adaptive live
  path requires 20.3.18+ on Nexus or 21.4.3+ on Omega from the matching branch.
- Python modules that import Kodi APIs must run inside Kodi or with explicit test
  mocks. Type stubs are for static analysis, not an executable Kodi runtime.

The permanent ID has its own settings and session namespace. Earlier development
installations are separate add-ons: do not silently import their account data,
tokens or device identities. New installations start with blank account fields
and live TV disabled. An identity change is not a same-ID update or proof of
installation/migration correctness.

## Local checks

Run the standard-library offline suite from the project root:

```sh
python3 -B -m unittest discover -s tests -v
```

Tests use synthetic inputs, temporary profiles and mocked Kodi APIs. They do not
sign in to a real account or establish native playback, audio output, rendering,
cross-platform coverage or long-session reliability.

For static validation, prepare a runtime-only directory named
`plugin.video.tastemade` with the package contents below. With Kodi Agent Toolkit
and its isolated checker/stub environment installed, replace the example paths:

```sh
python -m kodi_agent_toolkit.cli validate /path/to/plugin.video.tastemade --branch nexus --cache /path/to/index-cache
```

Use the correct branch and matching stubs for any additional version validation.
Inspect every required stage and retain warnings; a zero process exit alone is
not proof of success. Offline replay can leave the website URL check unverified.
Successful static checks do not prove installation or native Kodi acceptance.

Known implementation limits include provider bootstrap/bundle discovery that can
break when the service changes, no cross-invocation token-refresh lock, and no
complete cross-platform private-storage policy. Live-session expiry/refresh and
full-episode reliability still need broader native testing. Duration metadata is
left unset because the provider's units have not been conclusively verified.

## Standalone ZIP layout

Do not ZIP the entire checkout or re-label GitHub's automatic source archive as a
release. Build from this explicit runtime allowlist, with **one top-level folder**
named `plugin.video.tastemade/` and `addon.xml` directly inside it:

```text
plugin.video.tastemade/
  LICENSE.txt
  README.md
  addon.xml
  default.py
  resources/ARTWORK-NOTICE.txt
  resources/icon.png
  resources/fanart.jpg
  resources/settings.xml
  resources/language/resource.language.en_gb/strings.po
  resources/lib/auth.py
  resources/lib/catalog_metadata.py
  resources/lib/catalogue.py
  resources/lib/diagnostics.py
  resources/lib/live_playback.py
  resources/lib/plugin.py
  resources/lib/service.py
```

Keep tests, build tools, contributor documentation, Git metadata, local reports,
other ZIPs, credentials, profiles, settings values and caches out of the package.
The root README is included for reference; its contributor link is intended for
the online source tree, not as an additional runtime dependency.

Before attaching a package to a release:

1. Choose the intended version and ensure the manifest, ZIP filename and release
   tag agree. Keep historical development packages and evidence unchanged.
2. Check the ZIP's member paths, single root, CRCs and extracted file bytes. Reject
   duplicate entries, absolute paths, traversal paths and unrelated files.
3. Confirm manifest/settings identity, declared entry point, optional dependency,
   real relative artwork paths, blank account defaults and live TV off.
4. Validate the exact extracted runtime tree and record every stage and warning.
5. Separately test installation, settings and relevant browsing/playback behavior
   on an explicitly authorized test device. Static tests are not that acceptance.
6. Publish the prepared ZIP as a release asset. Do not describe a source archive
   or an unpublished local build as an available installation package.

This project is a video add-on, not a Kodi repository add-on. A future separate
Kodi repository will need its own repository package, index/checksum and hosted
add-on packages. Do not advertise its installation URL or automatic updates until
that distribution path actually exists.

## Artwork

`tools/build_addon_art.py` renders the original static icon and fanart using
Pillow at **build time only**. Neither Pillow nor that tool is a runtime dependency.
Keep the binary Git attributes for images so checkout/staging cannot normalize
their bytes. Preserve the artwork notice and license; do not add official logos,
third-party images or fabricated Kodi screenshots without appropriate provenance
and permission.

## Security and diagnostics

Account settings and session storage are private but **not encrypted**. Python
diagnostics must stay sanitized; native Kodi/player logs can contain sensitive
media/session URLs and must be reviewed before sharing. Do not commit or attach
accounts, bearer caches, cookies, profiles, private settings or raw private logs.
Do not weaken TLS, entitlement, URL or credential-forwarding checks.

The resolver supports entitled, provider-declared unencrypted HLS only. Preserve
the original VOD master/external-audio linkage and the optional direct ISA live
path; do not add a secret-forwarding media proxy or silent player fallback.

Before making an existing private repository public, review **Git history as well
as the current tree**. Removing a document from the current checkout does not
erase earlier commits. Never rewrite shared history or expose local operational
records as part of a routine documentation change.
