"""One live HLS player with explicit, user-consented native ISA setup."""
import re
from urllib.parse import urlencode

from diagnostics import diagnostic_stage, report
from service import MEDIA_USER_AGENT, ServiceError


INPUTSTREAM_ERROR = (
    'Live TV requires enabled InputStream Adaptive 20.3.18 or later on Kodi 20, '
    'or 21.4.3 or later on Kodi 21. Install, enable or update it through Kodi Add-ons.'
)
INPUTSTREAM_CANCELLED = 'InputStream Adaptive setup cancelled. VOD and browsing are unchanged.'
ISA_ID = 'inputstream.adaptive'


def ensure_inputstream(addon_factory, has_addon, confirm, execute, heading):
    """Offer one native action only when an enabled ISA handle is unavailable.

    Callers enter only after a user enables live TV and selects a channel. Kodi
    retains its own confirmation/permissions. A builtin return is not success:
    obtain a fresh enabled handle and version afterward. No retries or fallback.
    """
    try:
        isa = addon_factory(ISA_ID)
    except Exception:
        # Missing/disabled is a normal setup case, not a raw exception to log.
        isa = None
    if isa is None:
        try:
            installed = has_addon('System.HasAddon(inputstream.adaptive)')
            operation = 'EnableAddon' if installed else 'InstallAddon'
            message = (
                'InputStream Adaptive is installed but disabled. Open Kodi\'s enable confirmation now?'
                if installed else
                'Live TV needs InputStream Adaptive. Open Kodi\'s installer now? '
                'Kodi may ask you to confirm; VOD does not require it.'
            )
            accepted = confirm(heading, message)
        except Exception as error:
            report('live.inputstream', error)
            raise ServiceError(INPUTSTREAM_ERROR) from None
        if not accepted:
            raise ServiceError(INPUTSTREAM_CANCELLED) from None
        try:
            # InstallModal/EnableAddon are synchronous native UI operations.
            # wait=True has no Python deadline; do not add an automatic retry.
            execute(operation + '(inputstream.adaptive)', wait=True)
            isa = addon_factory(ISA_ID)
        except Exception as error:
            report('live.inputstream', error)
            raise ServiceError(INPUTSTREAM_ERROR) from None
    try:
        version = isa.getAddonInfo('version')
    except Exception as error:
        report('live.inputstream', error)
        raise ServiceError(INPUTSTREAM_ERROR) from None
    return live_properties(version)


def live_properties(version):
    """Use only the common 20/21 API and the evidenced manifest-type gate.

    The 21.x maintenance floor includes manifest-header and ad/quality fixes.
    ISA (not this add-on) owns manifest refreshes, redirects and quality choice.
    """
    with diagnostic_stage('live.inputstream'):
        match = re.fullmatch(r'([0-9]{1,3})\.([0-9]{1,3})\.([0-9]{1,3})(?:\.[0-9]{1,5})?', version) if isinstance(version, str) else None
        numbers = tuple(int(part) for part in match.groups()) if match else ()
        if not ((numbers and numbers[0] == 20 and numbers >= (20, 3, 18)) or
                (numbers and numbers[0] == 21 and numbers >= (21, 4, 3))):
            raise ServiceError(INPUTSTREAM_ERROR)
        # Only this public header is evidenced; never accept an API header map.
        headers = urlencode({'User-Agent': MEDIA_USER_AGENT})
        properties = {
            'inputstream': 'inputstream.adaptive', 'IsPlayable': 'true',
            'inputstream.adaptive.manifest_headers': headers,
            'inputstream.adaptive.stream_headers': headers,
        }
        if numbers[0] == 20:
            properties['inputstream.adaptive.manifest_type'] = 'hls'
        return properties
