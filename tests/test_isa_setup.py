"""Pure ISA consent/setup callbacks: no Kodi imports or external I/O."""
from contextlib import ExitStack
import logging
from pathlib import Path
import sys
import traceback
import unittest
from unittest.mock import ANY, MagicMock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'resources' / 'lib'))
import diagnostics
import live_playback
import service


MARKER = 'SYNTHETIC_SENSITIVE_SENTINEL'
ADDON_ID = 'inputstream.adaptive'
CONDITION = 'System.HasAddon(inputstream.adaptive)'
HEADING = 'Fixture add-on'
PROPERTIES = {
    'inputstream': ADDON_ID,
    'IsPlayable': 'true',
    'inputstream.adaptive.manifest_headers': 'User-Agent=Mozilla%2F5.0',
    'inputstream.adaptive.stream_headers': 'User-Agent=Mozilla%2F5.0',
}


class SensitiveSentinel(Exception):
    category = MARKER
    status = MARKER
    code = MARKER

    def __str__(self):
        raise AssertionError('SensitiveSentinel must not be formatted')


class InputstreamSetupTests(unittest.TestCase):
    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.lines = []
        diagnostics.configure(self.lines.append)
        self.addCleanup(diagnostics.configure)
        self.isa = MagicMock()
        self.isa.getAddonInfo.return_value = '20.3.18'
        self.fresh = MagicMock()
        self.fresh.getAddonInfo.return_value = '21.4.3'
        self.factory = MagicMock(return_value=self.isa)
        self.has_addon = MagicMock(return_value=False)
        self.confirm = MagicMock(return_value=False)
        self.execute = MagicMock(return_value=None)
        self.properties = stack.enter_context(patch.object(
            live_playback, 'live_properties', wraps=live_playback.live_properties))
        self.python_log = stack.enter_context(patch.object(logging.Logger, '_log'))
        self.fetch = stack.enter_context(patch.object(
            service, 'fetch', side_effect=AssertionError('No network in setup tests.')))
        self.request = stack.enter_context(patch.object(
            service, 'json_request', side_effect=AssertionError('No API in setup tests.')))
        self.events = MagicMock()
        for name, mock in [('factory', self.factory), ('has_addon', self.has_addon),
                           ('confirm', self.confirm), ('execute', self.execute),
                           ('version', self.isa.getAddonInfo),
                           ('fresh_version', self.fresh.getAddonInfo),
                           ('properties', self.properties)]:
            self.events.attach_mock(mock, name)

    def setup_inputstream(self):
        return live_playback.ensure_inputstream(
            self.factory, self.has_addon, self.confirm, self.execute, HEADING)

    def unavailable(self, installed=False, error=None):
        # Kodi's SDK constructor exposes enabled add-ons only. Visibility also
        # includes an installed but disabled add-on.
        self.factory.side_effect = [error or SensitiveSentinel(MARKER), self.fresh]
        self.has_addon.return_value = installed

    def reset_calls(self):
        self.events.reset_mock()
        self.lines.clear()
        self.python_log.reset_mock()

    def assert_prompt(self, installed):
        self.has_addon.assert_called_once_with(CONDITION)
        self.confirm.assert_called_once()
        args, kwargs = self.confirm.call_args
        self.assertEqual(kwargs, {})
        self.assertEqual(len(args), 2)
        self.assertEqual(args[0], HEADING)
        self.assertIsInstance(args[1], str)
        self.assertIn('inputstream', args[1].casefold())
        self.assertIn('enabl' if installed else 'install', args[1].casefold())
        self.assertNotIn(MARKER, args[1])
        return args[1]

    def assert_fixed_error(self, message=None):
        expected = live_playback.INPUTSTREAM_ERROR if message is None else message
        with self.assertRaises(service.ServiceError) as result:
            self.setup_inputstream()
        self.assertEqual(str(result.exception), expected)
        rendered = ''.join(traceback.format_exception(result.exception))
        self.assertNotIn(MARKER, rendered)
        self.assertNotIn('SensitiveSentinel', rendered)

    def assert_exception_metadata(self):
        self.assertTrue(any(
            'stage=live.inputstream category=unexpected http_status=none exception=OtherError' in line
            for line in self.lines), self.lines)

    def assert_no_setup(self):
        self.has_addon.assert_not_called()
        self.confirm.assert_not_called()
        self.execute.assert_not_called()
        self.factory.assert_called_once_with(ADDON_ID)
        self.fresh.getAddonInfo.assert_not_called()

    def assert_accepted_once(self, installed):
        self.assert_prompt(installed)
        command = ('EnableAddon' if installed else 'InstallAddon') + '(' + ADDON_ID + ')'
        self.execute.assert_called_once_with(command, wait=True)
        self.assertEqual(self.factory.call_args_list, [call(ADDON_ID), call(ADDON_ID)])
        self.isa.getAddonInfo.assert_not_called()

    def tearDown(self):
        self.fetch.assert_not_called()
        self.request.assert_not_called()
        emitted = '\n'.join(self.lines) + repr(self.python_log.call_args_list)
        for private in [MARKER, 'SensitiveSentinel', 'https://', 'Authorization', 'Bearer']:
            self.assertNotIn(private, emitted)
        for line in self.lines:
            self.assertRegex(line, r'^Tastemade diagnostic stage=[a-z_.]+ category=[a-z_]+ '
                                  r'http_status=(none|[1-5][0-9]{2}) exception=[A-Za-z]+$')

    def test_enabled_supported_version_needs_no_visibility_consent_or_builtin(self):
        for version in ['20.3.18', '21.4.3']:
            with self.subTest(version=version):
                self.reset_calls()
                self.isa.getAddonInfo.return_value = version
                expected = dict(PROPERTIES)
                if version.startswith('20.'):
                    expected['inputstream.adaptive.manifest_type'] = 'hls'
                self.assertEqual(self.setup_inputstream(), expected)
                self.assertEqual(self.events.mock_calls, [
                    call.factory(ADDON_ID), call.version('version'), call.properties(version)])
                self.assert_no_setup()
                self.assertEqual(self.lines, [])

    def test_enabled_too_old_only_gives_instructions_without_install_or_enable(self):
        for version in ['20.3.17', '21.4.2']:
            with self.subTest(version=version):
                self.reset_calls()
                self.isa.getAddonInfo.return_value = version
                self.assert_fixed_error()
                self.isa.getAddonInfo.assert_called_once_with('version')
                self.properties.assert_called_once_with(version)
                self.assert_no_setup()

    def test_enabled_malformed_or_unsupported_version_never_prompts_for_update(self):
        for version in ['', None, '20.3.18-' + MARKER, '22.0.0']:
            with self.subTest(version_type=type(version).__name__):
                self.reset_calls()
                self.isa.getAddonInfo.return_value = version
                self.assert_fixed_error()
                self.isa.getAddonInfo.assert_called_once_with('version')
                self.assert_no_setup()

    def test_enabled_version_lookup_failure_is_fixed_and_metadata_only(self):
        self.isa.getAddonInfo.side_effect = SensitiveSentinel(MARKER)
        self.assert_fixed_error()
        self.isa.getAddonInfo.assert_called_once_with('version')
        self.properties.assert_not_called()
        self.assert_no_setup()
        self.assert_exception_metadata()

    def assert_declined(self, installed):
        self.unavailable(installed)
        cancelled = live_playback.INPUTSTREAM_CANCELLED
        self.assertIsInstance(cancelled, str)
        self.assertTrue(cancelled)
        self.assertNotEqual(cancelled, live_playback.INPUTSTREAM_ERROR)
        self.assert_fixed_error(cancelled)
        self.assert_prompt(installed)
        self.assertEqual(self.events.mock_calls, [
            call.factory(ADDON_ID), call.has_addon(CONDITION), call.confirm(HEADING, ANY)])
        self.execute.assert_not_called()
        self.isa.getAddonInfo.assert_not_called()
        self.fresh.getAddonInfo.assert_not_called()
        self.properties.assert_not_called()

    def test_missing_declined_is_cancelled_without_action_or_fresh_check(self):
        self.assert_declined(False)

    def test_disabled_declined_is_cancelled_without_action_or_fresh_check(self):
        self.assert_declined(True)

    def assert_setup_success(self, installed):
        for builtin_result in [None, 0]:
            with self.subTest(builtin_result=builtin_result):
                self.reset_calls()
                self.unavailable(installed)
                self.confirm.return_value = True
                self.execute.return_value = builtin_result
                self.assertEqual(self.setup_inputstream(), PROPERTIES)
                self.assert_accepted_once(installed)
                self.assertEqual(self.events.mock_calls, [
                    call.factory(ADDON_ID), call.has_addon(CONDITION), call.confirm(HEADING, ANY),
                    call.execute(('EnableAddon' if installed else 'InstallAddon') + '(' + ADDON_ID + ')',
                                 wait=True),
                    call.factory(ADDON_ID), call.fresh_version('version'), call.properties('21.4.3')])

    def test_missing_accepted_installs_once_then_uses_fresh_enabled_sdk_and_version(self):
        self.assert_setup_success(False)

    def test_disabled_accepted_enables_once_then_uses_fresh_enabled_sdk_and_version(self):
        self.assert_setup_success(True)

    def test_native_cancel_or_unavailability_is_not_success_from_none_or_zero(self):
        for installed in [False, True]:
            for builtin_result in [None, 0]:
                with self.subTest(installed=installed, builtin_result=builtin_result):
                    self.reset_calls()
                    self.unavailable(installed)
                    self.factory.side_effect = [SensitiveSentinel(MARKER), SensitiveSentinel(MARKER)]
                    self.confirm.return_value = True
                    self.execute.return_value = builtin_result
                    self.assert_fixed_error()
                    self.assert_accepted_once(installed)
                    self.fresh.getAddonInfo.assert_not_called()
                    self.properties.assert_not_called()
                    self.assert_exception_metadata()

    def test_execute_failure_has_no_retry_fallback_or_fresh_factory_check(self):
        for installed in [False, True]:
            with self.subTest(installed=installed):
                self.reset_calls()
                self.unavailable(installed)
                self.confirm.return_value = True
                self.execute.side_effect = SensitiveSentinel(MARKER)
                self.assert_fixed_error()
                self.assert_prompt(installed)
                command = ('EnableAddon' if installed else 'InstallAddon') + '(' + ADDON_ID + ')'
                self.execute.assert_called_once_with(command, wait=True)
                self.factory.assert_called_once_with(ADDON_ID)
                self.fresh.getAddonInfo.assert_not_called()
                self.properties.assert_not_called()
                self.assert_exception_metadata()

    def test_fresh_version_lookup_is_required_even_after_native_success(self):
        for installed in [False, True]:
            with self.subTest(installed=installed):
                self.reset_calls()
                self.unavailable(installed)
                self.confirm.return_value = True
                self.fresh.getAddonInfo.side_effect = SensitiveSentinel(MARKER)
                self.assert_fixed_error()
                self.assert_accepted_once(installed)
                self.fresh.getAddonInfo.assert_called_once_with('version')
                self.properties.assert_not_called()
                self.assert_exception_metadata()

    def assert_fresh_bad_version(self, installed):
        for version in ['20.3.17', '21.4.2', '', '21.4.3-' + MARKER]:
            with self.subTest(version_type=type(version).__name__):
                self.reset_calls()
                self.unavailable(installed)
                self.confirm.return_value = True
                self.fresh.getAddonInfo.return_value = version
                self.assert_fixed_error()
                self.assert_accepted_once(installed)
                self.fresh.getAddonInfo.assert_called_once_with('version')
                self.properties.assert_called_once_with(version)

    def test_too_old_or_malformed_new_install_does_not_chain_to_enable_or_retry(self):
        self.assert_fresh_bad_version(False)

    def test_too_old_or_malformed_fresh_enable_does_not_install_or_retry(self):
        self.assert_fresh_bad_version(True)

    def test_visibility_failure_is_fixed_metadata_only_without_prompt_or_action(self):
        self.unavailable()
        self.has_addon.side_effect = SensitiveSentinel(MARKER)
        self.assert_fixed_error()
        self.has_addon.assert_called_once_with(CONDITION)
        self.factory.assert_called_once_with(ADDON_ID)
        self.confirm.assert_not_called()
        self.execute.assert_not_called()
        self.fresh.getAddonInfo.assert_not_called()
        self.properties.assert_not_called()
        self.assert_exception_metadata()

    def test_consent_failure_is_fixed_metadata_only_without_action_or_fresh_check(self):
        for installed in [False, True]:
            with self.subTest(installed=installed):
                self.reset_calls()
                self.unavailable(installed)
                self.confirm.side_effect = SensitiveSentinel(MARKER)
                self.assert_fixed_error()
                self.assert_prompt(installed)
                self.factory.assert_called_once_with(ADDON_ID)
                self.execute.assert_not_called()
                self.fresh.getAddonInfo.assert_not_called()
                self.properties.assert_not_called()
                self.assert_exception_metadata()

    def test_consent_message_is_fixed_human_text_not_constructor_error_details(self):
        for installed in [False, True]:
            messages = []
            for error in [RuntimeError('https://fixture.invalid/?token=' + MARKER),
                          SensitiveSentinel(MARKER)]:
                with self.subTest(installed=installed, error_type=type(error).__name__):
                    self.reset_calls()
                    self.unavailable(installed, error)
                    self.assert_fixed_error(live_playback.INPUTSTREAM_CANCELLED)
                    messages.append(self.assert_prompt(installed))
                    self.factory.assert_called_once_with(ADDON_ID)
                    self.execute.assert_not_called()
            self.assertEqual(messages[0], messages[1])


if __name__ == '__main__':
    unittest.main()
