# Tastemade for Kodi

An unofficial Kodi add-on for browsing Tastemade shows, movies, seasons and
episodes, with optional live TV.

**Not affiliated with or endorsed by Tastemade.** An eligible Tastemade account
and the appropriate content entitlement are required for playback. This add-on
does not bypass subscriptions, purchases, regional restrictions or DRM.

## Requirements

- **Kodi 20 (Nexus) or Kodi 21 (Omega).**
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

This GitHub project currently contains a standalone video add-on, **not a Kodi
add-on repository**. Installation and updates use packaged add-on ZIP files.

1. Open the project's [Releases](https://github.com/kcook98765/plugin.video.tastemade/releases)
   page and download the **add-on ZIP attached to a release**. If no installation
   ZIP is listed, an installable release has not been published yet.
   Do not use GitHub's **Code → Download ZIP** or the automatic **Source code**
   archives as the installation package.
2. Save the ZIP somewhere Kodi can access, such as your device's Downloads folder
   or a network share.
3. In Kodi, open **Settings → System → Add-ons** and enable **Unknown sources**
   if needed. Read Kodi's warning and only install packages from sources you trust.
4. Open **Settings → Add-ons → Install from zip file** and select the downloaded
   add-on ZIP. Wait for the installation notification.
5. Open **Add-ons → Video add-ons → Tastemade**.

Menu wording can vary slightly with your Kodi skin. You can turn Unknown sources
off again after installing; it may be needed again for a later manual update.

### Future Kodi repository installation

A separate Kodi add-on repository is planned for this and other add-ons. Once
published, you will install that repository's ZIP, then use **Install from
repository → [repository name] → Video add-ons → Tastemade**. The repository name
and download link will be added here when available.

That installation route and its update feed are **not available from this
standalone project yet**. For now, use a packaged standalone ZIP when available.

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

Until the separate Kodi repository is available, check this project's Releases
page and manually install a newer packaged ZIP using **Install from zip file**.
Installing a newer version with the same add-on ID normally preserves settings;
you do not need to uninstall or clear data first. This standalone GitHub project
does not supply an automatic Kodi update feed.

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

The add-on and its original bundled artwork are licensed under the
[MIT license](LICENSE.txt). Tastemade content and trademarks belong to their
respective owners and are not redistributed or licensed by this project. The
bundled icon and background are original generic artwork, not official branding;
see the [artwork notice](resources/ARTWORK-NOTICE.txt).

For source checks and packaging guidance, see
[CONTRIBUTING.md](https://github.com/kcook98765/plugin.video.tastemade/blob/main/CONTRIBUTING.md).
