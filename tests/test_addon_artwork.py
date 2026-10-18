"""Bundled original artwork/metadata contracts; standard library only."""
import hashlib
from pathlib import Path
import struct
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]


def jpeg_size(payload):
    if payload[:2] != b'\xff\xd8':
        raise ValueError('Not JPEG')
    cursor = 2
    while cursor < len(payload):
        if payload[cursor] != 0xff:
            raise ValueError('Malformed JPEG marker')
        while payload[cursor] == 0xff:
            cursor += 1
        marker = payload[cursor]
        cursor += 1
        if marker in (0xd8, 0xd9):
            continue
        length = int.from_bytes(payload[cursor:cursor + 2], 'big')
        if length < 2:
            raise ValueError('Malformed JPEG length')
        if marker in (0xc0, 0xc1, 0xc2):
            height, width = struct.unpack('>HH', payload[cursor + 3:cursor + 7])
            return width, height
        cursor += length
    raise ValueError('No JPEG dimensions')


class AddonArtworkTests(unittest.TestCase):
    def setUp(self):
        self.root = ET.parse(ROOT / 'addon.xml').getroot()
        self.metadata = self.root.find("extension[@point='xbmc.addon.metadata']")

    def test_manifest_declares_real_relative_icon_and_fanart_files(self):
        assets = self.metadata.find('assets')
        self.assertIsNotNone(assets)
        self.assertEqual([(node.tag, node.text) for node in assets], [
            ('icon', 'resources/icon.png'), ('fanart', 'resources/fanart.jpg')])
        for node in assets:
            path = ROOT / node.text
            self.assertTrue(path.is_file())
            self.assertFalse(path.is_symlink())
            self.assertNotIn('://', node.text)
            self.assertNotIn('..', Path(node.text).parts)
            self.assertEqual(node.text, path.relative_to(ROOT).as_posix())

    def test_icon_is_exact_opaque_512_square_png(self):
        payload = (ROOT / 'resources/icon.png').read_bytes()
        self.assertEqual(payload[:8], b'\x89PNG\r\n\x1a\n')
        self.assertEqual(struct.unpack('>II', payload[16:24]), (512, 512))
        self.assertEqual(payload[24:26], bytes([8, 2]))  # RGB, not transparent RGBA.
        self.assertEqual(hashlib.sha256(payload).hexdigest(),
                         '6ef2500f9acecec194fdf850e34397fd8f5354d20d4efc3bc4f353948fdc5814')

    def test_fanart_is_reviewed_1920_landscape_jpeg_under_checker_cap(self):
        payload = (ROOT / 'resources/fanart.jpg').read_bytes()
        self.assertEqual(jpeg_size(payload), (1920, 1080))
        self.assertLessEqual(len(payload), 1024000)
        self.assertEqual(hashlib.sha256(payload).hexdigest(),
                         '418cf98a6cee97d3ee438e88b2a2d0fbc9df25c44ef4362fcb342d72135296b9')

    def test_artwork_notice_and_reproducible_build_tool_are_present(self):
        notice = (ROOT / 'resources/ARTWORK-NOTICE.txt').read_text()
        self.assertIn('original geometric artwork', notice)
        self.assertIn('not screenshots', notice)
        self.assertTrue((ROOT / 'tools/build_addon_art.py').is_file())
        dependencies = {node.get('addon') for node in self.root.findall('requires/import')}
        self.assertEqual(dependencies, {'xbmc.python', 'inputstream.adaptive'})

    def test_user_facing_details_are_rich_honest_and_no_private_source_link(self):
        summary = self.metadata.findtext('summary')
        description = self.metadata.findtext('description')
        disclaimer = self.metadata.findtext('disclaimer')
        self.assertIn('Unofficial', summary)
        self.assertNotIn('prototype', summary.lower())
        for word in ('seasons', 'episodes', 'InputStream Adaptive'):
            self.assertIn(word, description)
        self.assertIn('not affiliated', disclaimer.lower())
        self.assertIn('Media/session URLs', disclaimer)
        self.assertEqual(self.metadata.findtext('license'), 'MIT')
        self.assertIsNone(self.metadata.find('source'))
        self.assertEqual(self.metadata.findtext('website'), 'https://www.tastemade.com/')
        self.assertLess(len(self.metadata.findtext('news')), 1500)

    def test_no_fake_gallery_or_service_or_namespace_change(self):
        self.assertEqual(self.root.get('id'), 'plugin.video.tastemade.workstation')
        self.assertEqual(self.root.get('version'), '0.1.0')
        self.assertFalse(self.metadata.findall('assets/screenshot'))
        self.assertFalse(self.root.findall("extension[@point='xbmc.service']"))
        self.assertEqual(self.root.find("requires/import[@addon='inputstream.adaptive']").get('optional'), 'true')


if __name__ == '__main__':
    unittest.main()
