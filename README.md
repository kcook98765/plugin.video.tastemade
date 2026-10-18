# Tastemade — unofficial Kodi add-on

Kodi 20.5/Nexus and Kodi 21.3/Omega source targets. Unofficial; not affiliated
with Tastemade. Static checks and transport tests do not prove native playback.

Configure an existing account manually through Account settings. Both defaults
are blank; the password control is masked, not encrypted. Never export the
runtime profile. Verify login creates or reuses the viewing session and reports
only a fixed, non-identifying status. Playback reuses saved authentication.

Session storage is restricted to the add-on profile's auth/ subdirectory (0700)
and atomically replaced session.json (0600). It contains the viewing bearer,
a stable web-device ID and a salted credential binding, not a second copy of
email/password. This is private storage, NOT encrypted storage. Authentication
is checked with /user; an authenticated 401 triggers the official POST
/user/refresh-token and one retry. No JWT lifetime or refresh-token field is
invented. Rejected/expired sessions require Verify login; temporary network
failures preserve the saved session. Explicit Verify login can sign in again.

Log out clears the local bearer and keeps the profile signed out until Verify
login (or an account change). It does not revoke other devices' sessions.
Changing either account field invalidates the cache after settings closes or
before the next authenticated operation, including changes made outside this
add-on menu. Reusable credentials and full playback URLs are never deliberately
logged by the add-on's Python diagnostics or included in plugin routes.
Kodi/InputStream Adaptive logs can contain provider media/session URLs; this is
accepted behavior, not a promise that native logs are safe to publish. Account
access/refresh tokens, passwords, usernames and cookies must still be protected.

Settings/login/logout actions replace their action route with the root after
their modal closes, including on errors. Playback failures stay in the listing.
Root is offline and has four entries. Identical menu reference/label pairs are
deduplicated, preserving distinct pages. Public browsing needs no account.

Errors distinguish authenticated-session rejection, explicit GEO blockers,
membership/product/purchase blockers, network/rate-limit/server failures and
unsupported streams. A generic 403 is not misrepresented as a password or
region error. Raw responses, GraphQL messages and untrusted blocker messages
are never displayed. Unexpected failures remain generic for privacy.

Only entitled, provider-declared unencrypted direct HLS is selected. VOD keeps
its original validated master (including external audio), existing strict URL/
manifest checks, and native playback with only the public media User-Agent.
No DRM, purchase, geo bypass, download, secret importing or profile exporting.
Only this add-on directory is a package/deployment input. Private credentials,
tests and local validation candidates must NEVER be registered or deployed.

Catalogue items include available descriptions, artwork and typed video tags.
Complete bounded episode inventories offer numeric seasons and ordered episodes;
curated playlists retain provider order. Remaining: computed playlists/search, resilient bootstrap/bundle discovery,
concurrent-invocation token refresh locking, cross-platform private-storage
policy, and broader native/network acceptance. Audio, pause state, seeking,
media-clock and native Information-page claims require observed evidence.

## Optional live TV

**Playback -> Enable live TV** is off by default. Browsing, catalogue metadata,
account actions and VOD do not require or check InputStream Adaptive (ISA).
Channel entries remain visible; selecting one while disabled explains the option.

To opt in, enable live TV in this add-on's settings and select a channel. If ISA
is missing/disabled, the add-on offers one install/enable action through Kodi's
normal confirmation UI. Nothing is installed or enabled without consent. Cancel
returns to the listing without affecting VOD. A fresh enabled handle/version is
checked after the native action; a dispatch return alone is not success. The
manifest dependency stays optional, with no silent alternate-player fallback. Supported
ISA release floors are **20.3.18 on Nexus** and **21.4.3 on Omega**. Kodi's version
number is not ISA's version number. If setup fails/is cancelled or ISA is too old,
playback stops before account access or stream requests. Existing old versions
need an update through Kodi Add-ons; InstallAddon is not used as an updater.

One live path passes the provider's original HTTPS HLS master and unchanged
playback query to ISA. The resolver retains authentication, entitlement, region
and declared-DRM checks plus lightweight URL/known-credential guards. Media gets
only the evidenced public User-Agent, encoded separately in ISA manifest/stream
header properties. No account/API headers, cookies, license properties, TLS
overrides or query-rewriting properties are forwarded. The explicit HLS type is
set for ISA 20; supported ISA 21 versions auto-detect it.

ISA owns HLS reloads, media redirects, rendition selection and ordinary HLS
discontinuities. Its user's quality settings are left alone. There is no proxy,
background service, localhost listener, playback descriptor, custom downloader
or ad filtering. A public stream test is not native ISA decoding or ad acceptance.

## Catalog pagination

The catalogue's **Home** entry is displayed as **VOD**. **Live TV** opens the
current live channel list directly, without Live Now -> Live Channels folders.
The live playlist is discovered from the provider's page reference at request
time, not a hardcoded ID; an unexpected ambiguous layout fails clearly instead
of choosing an arbitrary playlist. Browsing channels still needs neither ISA
nor sign-in; optional live playback checks apply only when Play is selected.

Root, catalogue, section and pagination folders include concise descriptions.
Season folders show actual episode counts as secondary labels. Available provider
summaries are preserved; fallback help is navigation guidance, not invented
programme metadata. Exact placement of summaries/counts depends on the Kodi skin.

Playlists and episode lists show up to 30 raw catalog items per page, with
Previous page and Next page links. Requests fetch at most 31 entries; the extra
lookahead determines whether more episodes exist even when the service omits
total/size/offset metadata. The lookahead is not consumed: it is the first item
of the next page, so page boundaries neither skip nor duplicate that item.
Episode lists are no longer capped at the original single 300-item request.
Known playlist totals are also honored; an empty page never offers Next page.
Previous page remains available on an empty nonzero page after catalog changes.
Invalid offsets/malformed paging responses fail with fixed sanitized messages.
The live catalog can change between requests; this is offset pagination, not a
snapshot guarantee. Search and computed playlists remain unsupported.

## Artwork and presentation

Series use suitable upstream landscape/portrait images in their corresponding
Kodi roles. Season folders reuse available parent-series artwork: no independent
season artwork was exposed by the sampled integration, and no covers/overlays
are generated. Episode stills remain thumbnails; a portrait is not stretched
into a landscape thumbnail. Seasons sort numerically, episodes sort within a
selected season, and curated lists remain unsorted/provider-ordered.

Missing/unsafe image values use a small fixed set of native Kodi textures;
episode placeholders do not invent posters that would override real stills.
Series fanart supplies season/episode backgrounds when available. The add-on's
own Information/browser artwork is bundled at resources/icon.png and
resources/fanart.jpg: original geometric plate/play imagery, not a provider logo
or programme image. Catalogue image selection is unchanged; absent programme
backgrounds still follow the native skin's behavior. No manifest declaration
points at a missing file. Generic
textures were verified against Estuary for Kodi 20.5/21.3; failed remote-image
fallback varies by skin/view and is not guaranteed by setting an icon field.
Browsing does not make blocking image-validation requests.

The original static artwork needs no runtime image library. Its reproducible
build tool uses the existing validation environment's Pillow only; that tool is
not an add-on entry point or dependency. See resources/ARTWORK-NOTICE.txt for
the original-art notice. No website image or generated UI mockup is presented
as a Kodi screenshot; the gallery is omitted until genuine capture files exist.

Titles/menus normalize HTML/entities/whitespace, summaries preserve paragraphs,
and headings identify the series/season. Unknown dates/numbers/duration remain
unset. Duration units were not conclusively verified. No view mode or user's
settings are forced. Back/selection behavior still requires native verification.

Season discovery requests at most 300 episodes. If that inventory is capped or
known incomplete, All episodes keeps the existing 30-item paged route rather
than silently truncating a series or inventing a complete season list.
