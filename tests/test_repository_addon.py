# SPDX-License-Identifier: BSD-3-Clause
"""
repository/addon.xml: which feed each Kodi reads. Kodi 21 (CoreELEC 21, 32-bit ARM) gets omega/, Kodi 22 and its
21.90+ pre-releases (CoreELEC 22, AArch64) get piers/, each checked by sha256.
"""

import json
import unittest
import xml.etree.ElementTree as ET

from collect_zips import SOURCES
from kodirepo import compare_versions

from .helpers import REPO

ADDON = ET.parse(REPO / 'repository' / 'addon.xml').getroot()


def feed_for(kodi_version):
    for folder in ADDON.iter('dir'):
        low, high = folder.get('minversion', '0'), folder.get('maxversion')
        if compare_versions(kodi_version, low) >= 0 and (high is None or compare_versions(kodi_version, high) <= 0):
            return folder.findtext('datadir').rstrip('/').rsplit('/', 1)[-1]
    return None


class RepositoryAddonTest(unittest.TestCase):
    def test_kodi_versions_reach_their_feed(self):
        for kodi, feed in (
            ('21.0.0', 'omega'),
            ('21.3.0', 'omega'),
            ('21.90.0', 'piers'),
            ('22.0.0', 'piers'),
            ('22.3.1', 'piers'),
            ('20.5.0', None),
            ('22.90.0', None),
        ):
            self.assertEqual(feed_for(kodi), feed, kodi)

    def test_every_feed_is_on_the_site_and_checked_by_sha256(self):
        self.assertEqual(ADDON.get('id'), 'repository.somepanic')
        for folder in ADDON.iter('dir'):
            name = folder.findtext('datadir').rstrip('/').rsplit('/', 1)[-1]
            base = f'https://somepanic.github.io/{name}/'
            self.assertEqual(folder.findtext('datadir'), base)
            self.assertEqual(folder.findtext('info'), base + 'addons.xml')
            self.assertEqual(folder.findtext('checksum'), base + 'addons.xml.sha256')
            self.assertEqual(folder.find('checksum').get('verify'), 'sha256')
            self.assertEqual(folder.findtext('hashes'), 'sha256')

    def test_the_page_describes_every_addon_the_repository_collects(self):
        catalog = json.loads((REPO / 'repository' / 'addons.json').read_text(encoding='utf-8'))

        self.assertEqual(set(catalog), {source['id'] for source in SOURCES})
        for addon_id, entry in catalog.items():
            self.assertEqual(set(entry), {'name', 'about', 'home', 'kind'}, addon_id)
            self.assertIn(entry['kind'], ('addon', 'skin'), addon_id)
            self.assertTrue(entry['home'].startswith('https://github.com/'), addon_id)
            self.assertTrue(entry['about'].endswith('.'), addon_id)

    def test_its_icon_is_there(self):
        icon = ADDON.findtext("extension[@point='xbmc.addon.metadata']/assets/icon")
        self.assertTrue((REPO / 'repository' / icon).is_file(), icon)
