# Tastemade for Kodi — private development repository

Unofficial experimental video add-on for **Kodi 20/Nexus**. Not affiliated with
or endorsed by Tastemade. The repository name does not change the add-on ID:
**`plugin.video.tastemade.workstation`**, version **0.1.0**.

## Installation

The exact generation-9 add-on source is at this repository's root, with
`addon.xml` at the root. For a private installation package, include **only the
nine source files listed in `PROVENANCE.json`**, preserving their relative
paths inside a top-level folder named `plugin.video.tastemade.workstation`.
Install that ZIP through Kodi **Settings → Add-ons → Install from zip file**.
Do not include tests, Git data, repository documentation, account data or caches.
No installable package or release is published by this repository.

Open the add-on's **Account settings**, enter the email/password for an existing
eligible official Tastemade account, save, and choose **Verify login**. Defaults
are blank and the password edit control is masked, not encrypted. Some
third-party channel subscriptions do not grant access in Tastemade's own apps.
Never share account-settings screenshots or export the private Kodi profile.

## Supported scope

- Public catalog browsing, 30-item playlist/episode pages and Previous/Next.
- Existing-account login, private session reuse, bounded server-driven refresh,
  local logout and account-change invalidation.
- Entitled **unencrypted, direct HTTPS HLS** playback only. DRM, purchases,
  geographic bypass, offline downloads and indirect/ad-insertion streams are
  not implemented. Do not assume the entire catalog is DRM-free.
- Fixed sanitized error messages; no raw account responses, credentials,
  bearer tokens or playback URLs are logged by the add-on.

## Verification and known limits

| Evidence | Result / limit |
| --- | --- |
| Kodi Nexus 20.5 | Authentication/session reuse, logout/re-login and a one-episode active-video observation across 60 seconds passed on the preceding generation-6 baseline. Three-series playback samples also passed on an earlier baseline. |
| Generation 9 | Bounded Kodi UI checks passed for playlist and episode Next/Previous, Back context and short final pages. No new playback test was performed for the pagination-only change. |
| Offline checks | 40 focused tests passed; Nexus syntax, manifest, packaging, types and official checker passed. Offline metadata URL checking remained unverified; optional artwork is absent. |
| Not verified | Audio output, actual paused state, seek distance, media-clock progression, genuine live expiry/refresh, live account changes and full-episode reliability. Active-video samples are not continuous playback telemetry. |
| Windows portable | User-reported native `OPENSSL_Uplink(...) no OPENSSL_Applink` error during online browsing and after saving account settings. **Windows authentication/playback remain unverified. This is not evidence of invalid credentials.** No SSL fix is claimed. |

The source still pins an observed official web bundle, uses the first supported
HLS variant, and lacks richer metadata, search, seasons and computed playlists.
The focused tests use synthetic data and mocks, not credentials or a real Kodi:

```sh
python3 -B -m unittest discover -s tests -v
```

All 40 tests were also rerun successfully in this standalone repository after
adapting only the test library-root and temporary-directory paths.

## Provenance, privacy and workflow

`PROVENANCE.json` records generation 9, the verified checkpoint commit and exact
file sizes/SHA256 hashes. All nine source files, including the original root
README and license notice, are unchanged. This `.github/README.md` is an
additional repository guide, not a replacement for the source README.

**This repository is not yet the registered Kodi Lab development source.**
Registration/grant/baseline/workspace migration is a separate task. Nothing here
changes existing registered sources, workspaces, deployments or installations.

Credentials, runtime settings, auth caches, logs, screenshots, ZIPs, MCP/OpenCode
configuration and workstation administration records are excluded. Git ignores
are not a substitute for reviewing what is staged. Session files are private
profile data protected by file permissions, **not encrypted storage**.

The source's existing **MIT License notice in `LICENSE.txt`** is retained
unchanged. No new license or ownership claim is added. Tastemade content and
trademarks are not licensed or redistributed by this repository.
