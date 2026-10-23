# Tastemade for Kodi

An unofficial Kodi add-on for browsing Tastemade shows, movies, seasons and
episodes, with optional live TV.

This is an unofficial Kodi add-on developed independently and is not affiliated
with, endorsed by, or sponsored by Tastemade. Tastemade and associated marks
belong to their respective owners. **Tastemade does not support this add-on.**
Use this project's issue tracker for add-on problems.

An eligible Tastemade account and the appropriate content entitlement are
required for playback. This add-on does not bypass subscriptions, purchases,
regional restrictions or DRM. No provider authorization for this integration
has been obtained or is claimed. The unresolved Tastemade terms-of-service
restriction remains a release risk; the project's MIT license does not grant
permission to use provider content, services or marks.

## Initial 0.1.0 release status

**0.1.0 is published in AI Kodi Repository for Kodi 21 (Omega) only.** See the
[release notes and recorded limitations](https://github.com/kcook98765/ai-kodi-repository/releases/tag/tastemade-0.1.0).
The frozen package was published on 2026-10-23 UTC (2026-10-22 Pacific).

Retained native evidence covers Linux Kodi 21.3 with Estuary: installation
through Kodi Lab's uploaded-plugin workflow, sampled navigation, login/session
reuse, video playback, pause/resume, one forward seek, stop, sequential logout
refusal and fresh authenticated playback. Kodi's GUI ZIP chooser and
public-repository installation/update have not been tested for this add-on.
Retained checks also passed 261 offline mocked tests and all six static stages
for Nexus and Omega; those checks supply no additional native acceptance.

Genuine provider-session expiry, native overlapping logout and native
missing-artwork fallback remain unobserved. Audible audio was unavailable on the
managed target because it has no audio device. Runtime acceptance remains
false/deferred; publication used the owner's scoped initial-release exceptions,
which expire on 2027-10-22 at 23:59:59 UTC and supply no provider permission.
Live TV remains experimental, off by default and outside the native acceptance
scope. Remote artwork returning 404 has no active fallback/retry.

The installation package is `plugin.video.tastemade-0.1.0.zip` (122,001 bytes),
with SHA-256:

```text
d21af0f89c118c2a4c789b656b27d6211a086cce961dc3501fa4ad00564fce87
```

This online guide has been updated separately. The frozen ZIP retains its
earlier README; its references to source-project Releases and a future
repository predate publication. Use the download locations below; the published
0.1.0 package bytes are unchanged.

## Requirements

- **Published catalog: Kodi 21 (Omega); native evidence is limited to Linux
  Kodi 21.3/Estuary.** Other Omega platforms have no native acceptance evidence.
- Kodi 20 (Nexus) is a source/API target with static checks only and is excluded
  from the initial catalog. Kodi 19 (Matrix) is outside the required
  `xbmc.python >=3.0.1` API floor. Kodi 22 (Piers) is unqualified and excluded;
  live playback rejects InputStream Adaptive 22.x. Manifest `platform=all`
  does not establish all-platform support.
- An internet connection. Browsing the catalogue does not require signing in.
- An eligible Tastemade account for playback; available content depends on your
  account and location.
- For optional live TV: **InputStream Adaptive 20.3.18 or newer on Nexus**, or
  **21.4.3 or newer on Omega**, from the matching Kodi branch. Availability varies
  by platform and Kodi distribution. VOD does not require InputStream Adaptive.

The add-on is under development. Service changes can affect browsing and
playback; complete reliability across all Kodi platforms is not guaranteed.

## Installation

### Standalone ZIP installation

This GitHub project contains the video add-on source, **not a Kodi repository
add-on**. No source-project Release asset currently exists. The published direct
download is the [AI Kodi Repository 0.1.0 package](https://kcook98765.github.io/ai-kodi-repository/packages/plugin.video.tastemade/plugin.video.tastemade-0.1.0.zip),
with a [SHA-256 sidecar](https://kcook98765.github.io/ai-kodi-repository/packages/plugin.video.tastemade/plugin.video.tastemade-0.1.0.zip.sha256).
The same frozen ZIP is available as a pinned
[GitHub Release asset](https://github.com/kcook98765/ai-kodi-repository/releases/download/tastemade-0.1.0/plugin.video.tastemade-0.1.0.zip)
in the distribution repository.

1. Download that packaged add-on ZIP and check its SHA-256 against the digest
   above and its published sidecar. Do not use GitHub's **Code → Download ZIP**
   or automatic **Source code** archives as an installation package.
2. Save the ZIP somewhere Kodi can access, such as your device's Downloads folder
   or a network share.
3. In Kodi, open **Settings → System → Add-ons** and enable **Unknown sources**
   if needed. Read Kodi's warning and only install packages from sources you trust.
4. Open **Settings → Add-ons → Install from zip file** and select the downloaded
   add-on ZIP. Wait for the installation notification.
5. Open **Add-ons → Video add-ons → Tastemade**.

Menu wording can vary slightly with your Kodi skin. You can turn Unknown sources
off again after installing; it may be needed again for a later manual update.

### AI Kodi Repository installation

The separate [AI Kodi Repository](https://kcook98765.github.io/ai-kodi-repository/)
provides its repository installer and **Tastemade 0.1.0 in the Omega catalog**.

1. Download the [repository.ai.kodi 0.1.0 installer](https://kcook98765.github.io/ai-kodi-repository/packages/repository.ai.kodi/repository.ai.kodi-0.1.0.zip)
   and its [SHA-256 sidecar](https://kcook98765.github.io/ai-kodi-repository/packages/repository.ai.kodi/repository.ai.kodi-0.1.0.zip.sha256).
   The existing installer SHA-256 is
   `f4ec0c67329e70516baa824606f9133ff95516bea0cfcee6370fa2ac7a0afdad`.
2. On Kodi 21, use **Settings → Add-ons → Install from zip file** to install
   the repository ZIP, enabling Unknown sources if needed.
3. Open **Install from repository → AI Kodi Repository → Video add-ons →
   Tastemade → Install**. Confirm the version is 0.1.0.
4. Open **Add-ons → Video add-ons → Tastemade**.

The repository installer has catalogs for several Kodi versions; that does not
mean every add-on is admitted or tested in every catalog. Tastemade is published
in Omega only.

## First-time setup

1. Open **Tastemade → Settings → Account**.
2. Enter your Tastemade email and password, then save the settings with **OK**.
3. Select **Verify login** in the add-on's main menu.
4. Open **Browse → VOD**, choose a programme, then select an episode or video.

Successful login does not guarantee access to every title: the service checks
your entitlement for each video. The add-on reuses its saved viewing session.
Use **Sign out** to clear the local session; this does not sign out other devices.

### Optional live TV

Live TV is **off by default**.

1. Open **Settings → Playback** and enable **Enable live TV (requires InputStream Adaptive)**.
2. Open **Browse → Live TV** and select a channel.
3. If InputStream Adaptive is missing or disabled, follow Kodi's installation or
   enable confirmation. Nothing is installed or enabled without your consent.

If the required InputStream Adaptive version is unavailable on your platform,
live TV cannot start. Update an older installed version through Kodi's Add-ons
manager. Cancelling setup returns to the listing; VOD remains available.

## Browsing

- **VOD** contains the service's available on-demand sections and programmes.
- **Live TV** opens the current channel list directly; browsing it does not enable
  live playback or require InputStream Adaptive.
- Series show season folders when a complete season list can be determined.
  **All episodes** is used when that inventory is incomplete.
- Use **Next page**, **Previous page** and Kodi's **Back** control to navigate.
- Descriptions, episode counts and artwork appear where supported by your skin
  and view. Kodi's normal views and playback controls are left unchanged.

Search and computed playlists are not currently supported. Only entitled,
provider-declared unencrypted HLS streams are supported; there is no download,
ad-filtering or DRM-bypass feature.

## Updates

AI Kodi Repository's Omega catalog is the update feed; updates also depend on
your Kodi update settings. The current published version is 0.1.0.
For manual updates, use only a newer reviewed package announced by this project
and choose **Install from zip file**. Source-project Release mirrors are not
currently provided. Installing a newer version with the same add-on ID normally
preserves settings; back up your private profile before updating. Public-origin
installation/update behavior still awaits native testing.

**For earlier testers:** the add-on ID is now `plugin.video.tastemade`. Earlier
development builds used a different ID, so this is a separate installation rather
than an in-place update of those builds. Enter your account settings again and
recreate any favourites or shortcuts. Old settings and sessions are not copied
or removed automatically.

## Troubleshooting and support

- **Login rejected:** check your account details and select **Verify login** again.
  A network failure, subscription restriction or regional block is not necessarily
  an incorrect password.
- **A title will not play:** confirm it is available to your account and location.
  Unsupported or DRM-protected streams cannot be played by this add-on.
- **Live TV will not start:** check the Playback setting and the installed
  InputStream Adaptive version, then try the channel again.
- **A catalogue page fails:** go Back and retry. Service/API changes may require
  an add-on update.

For reproducible problems, use [GitHub Issues](https://github.com/kcook98765/plugin.video.tastemade/issues).
Include the add-on version, Kodi version, operating system, InputStream Adaptive
version if relevant, and the steps and visible error message. **Do not post
credentials, saved profiles or unreviewed logs.**

## Privacy

Saved account settings and viewing sessions are **not encrypted**. Password
masking only hides the on-screen value. Protect your Kodi profile and backups;
do not share the add-on's settings or session files.

The add-on's Python diagnostics omit credentials, tokens and playback URLs, but
native Kodi/InputStream Adaptive logs **can contain media and session URLs**.
Review and redact logs before sharing them. Keep email addresses, passwords,
tokens, cookies and private network/device details out of public reports.

## License and development

The project's add-on code and original bundled artwork are licensed under the
[MIT license](LICENSE.txt). Tastemade content and trademarks belong to their
respective owners. The ZIP contains no video files, provider application code or
programme images. Programme artwork and service data are retrieved at runtime;
their absence from the ZIP does not resolve the provider terms restriction or
grant permission for their display. The bundled icon and background are original
generic artwork, not official branding; see the
[artwork notice](resources/ARTWORK-NOTICE.txt).

For source checks and packaging guidance, see
[CONTRIBUTING.md](https://github.com/kcook98765/plugin.video.tastemade/blob/main/CONTRIBUTING.md).
