# Tastemade Workstation — private prototype

Kodi 20.5/Nexus. Unofficial; not affiliated with Tastemade.

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
add-on menu. Tokens/passwords/URLs are never logged or included in plugin routes.

Settings/login/logout actions replace their action route with the root after
their modal closes, including on errors. Playback failures stay in the listing.
Root is offline and has four entries. Identical menu reference/label pairs are
deduplicated, preserving distinct pages. Public browsing needs no account.

Errors distinguish authenticated-session rejection, explicit GEO blockers,
membership/product/purchase blockers, network/rate-limit/server failures and
unsupported streams. A generic 403 is not misrepresented as a password or
region error. Raw responses, GraphQL messages and untrusted blocker messages
are never displayed. Unexpected failures remain generic for privacy.

Only entitled, unencrypted direct HLS is supported. Existing first-variant
selection and HTTPS/no-query/no-userinfo/no-encryption manifest checks remain.
No DRM, purchase, geo bypass, download, secret importing or profile exporting.
Only this add-on directory is a package/deployment input. Private credentials,
tests and local validation candidates must NEVER be registered or deployed.

Remaining: richer metadata, computed playlists,
search, locale strings for new messages, resilient bootstrap/bundle discovery,
quality selection, concurrent-invocation token refresh locking, cross-platform
private-storage policy, and broader network/stream reliability tests. Runtime
audio, pause state, seeking and media-clock claims require observed evidence.

## Catalog pagination

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
snapshot guarantee. Search, seasons and computed playlists remain unsupported.
