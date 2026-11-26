# SPDX-License-Identifier: BSD-3-Clause
"""
tools/collect_zips.py: the newest zip of every add-on, checked, for both feeds. Our add-ons come from their GitHub releases,
PM4K and Plex Uno unchanged from Don't Panic and Maybe Panic. The fake web answers at the real addresses.
"""

import hashlib
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import collect_zips as collect

from .helpers import FakeWeb, addon_xml, addon_zip, elf, sums

API = 'https://api.github.com/repos'
DONT_PANIC = 'https://raw.githubusercontent.com/pannal/dontpanickodi/master/omega/zips/'
MAYBE_PANIC = 'https://raw.githubusercontent.com/FilHarr/maybepanic/main/'
P3I = 'https://raw.githubusercontent.com/pannal/p3i_repo/master/omega/zips/'


def release(web, repo, tag, files):
    """A GitHub release of repo with files (name: bytes) and their SHA256SUMS."""
    files = dict(files, SHA256SUMS=sums(files))
    base = f'https://github.com/{repo}/releases/download/{tag}/'
    assets = [{'name': name, 'browser_download_url': base + name} for name in files]
    web.pages[f'{API}/{repo}/releases/latest'] = json.dumps({'tag_name': tag, 'assets': assets}).encode()
    for name, data in files.items():
        web.pages[base + name] = data


class World:
    """Every source as it stands: our releases, and the upstream Kodi feeds with an older version beside the newest."""

    def __init__(self):
        self.web = FakeWeb({})
        self.feeds = {}  # base URL: {add-on ID: {version: zip}}
        self.silomod = addon_zip('script.silomod', '0.1.0', name='SiloMod (SM4K)')
        self.jellymod = addon_zip('script.jellymod', '0.1.0', name='JellyMod (JM4K)')
        self.loguploader = addon_zip('script.pm4k.loguploader', '2.1.0')
        self.coretube = {
            'arm': addon_zip('browser.tizentube', '0.5.4', extra={'cobalt/cobalt': elf(1, 40)}),
            'aarch64': addon_zip('browser.tizentube', '0.5.4', extra={'cobalt/cobalt': elf(2, 183)}),
        }
        release(self.web, 'somepanic/SM4K', 'silomod-v0.1.0', {'script.silomod-0.1.0.zip': self.silomod})
        release(self.web, 'somepanic/JM4K', 'jellymod-v0.1.0', {'script.jellymod-0.1.0.zip': self.jellymod})
        release(
            self.web,
            'somepanic/script.pm4k.loguploader',
            'loguploader-v2.1.0',
            {'script.pm4k.loguploader-2.1.0.zip': self.loguploader},
        )
        release(
            self.web,
            'somepanic/CoreTube',
            'v0.5.4',
            {f'browser.tizentube-0.5.4-{arch}.zip': data for arch, data in self.coretube.items()},
        )

        self.newest = {}  # (base, add-on ID): the newest zip there
        self.offer(DONT_PANIC, 'script.plexmod', '1.0.6-rev1', '1.3.19')
        self.offer(DONT_PANIC, 'script.mcfontface', '0.0.9', '0.1.0')
        for skin in ('skin.plextuary', 'skin.plextuaryce', 'skin.plextuarycpm'):
            self.offer(DONT_PANIC, skin, '4.0.0-pm4k1.9', '4.0.0-pm4k1.15', gui='5.17.0')
        self.offer(P3I, 'skin.p3i.estuary', '8.8.9', '8.8.25', gui='5.17.0')
        for feed in ('zips/', 'piers/zips/'):
            self.offer(MAYBE_PANIC + feed, 'script.plexmod-uno', '0.4.3', '0.4.4')
        self.offer(MAYBE_PANIC + 'zips/', 'skin.plextuary-uno', '0.1.1', '0.1.2', gui='5.17.0')
        self.offer(MAYBE_PANIC + 'piers/zips/', 'skin.plextuary-uno', '22.0.0', '22.0.1', gui='5.18.0')
        for skin in ('skin.plextuaryce-uno', 'skin.plextuarycpm-uno'):
            self.offer(MAYBE_PANIC + 'zips/', skin, '0.1.2', '0.1.3', gui='5.17.0')
        for base, addons in self.feeds.items():
            root = ET.Element('addons')
            for addon_id, versions in addons.items():
                for version in versions:
                    root.append(ET.fromstring(addon_xml(addon_id, version)))
            index = ET.tostring(root, encoding='utf-8', xml_declaration=True)
            self.web.pages[base + 'addons.xml'] = index
            self.web.pages[base + 'addons.xml.md5'] = hashlib.md5(index).hexdigest().encode()

    def offer(self, base, addon_id, *versions, gui=None):
        """addon_id's versions in the Kodi feed at base, the last one the newest."""
        for version in versions:
            data = addon_zip(addon_id, version, gui=gui)
            self.feeds.setdefault(base, {}).setdefault(addon_id, {})[version] = data
            self.web.pages[f'{base}{addon_id}/{addon_id}-{version}.zip'] = data
        self.newest[(base, addon_id)] = self.feeds[base][addon_id][versions[-1]]


class CollectTest(unittest.TestCase):
    def setUp(self):
        self.world = World()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.staging = Path(self.tmp.name) / 'staging'

    def collect(self, token=None):
        return collect.collect(self.staging, fetch=self.world.web, token=token)

    def staged(self):
        manifest = json.loads((self.staging / 'manifest.json').read_text())
        return {(entry['feed'], entry['id']): entry for entry in manifest}

    def test_each_list_gets_what_its_kodi_is_offered_upstream(self):
        self.collect()

        staged = self.staged()
        world = self.world
        both = {
            'script.silomod': ('0.1.0', world.silomod),
            'script.jellymod': ('0.1.0', world.jellymod),
            'script.pm4k.loguploader': ('2.1.0', world.loguploader),
            'script.plexmod': ('1.3.19', world.newest[(DONT_PANIC, 'script.plexmod')]),
            'script.mcfontface': ('0.1.0', world.newest[(DONT_PANIC, 'script.mcfontface')]),
            'skin.plextuary': ('4.0.0-pm4k1.15', world.newest[(DONT_PANIC, 'skin.plextuary')]),
            'skin.plextuaryce': ('4.0.0-pm4k1.15', world.newest[(DONT_PANIC, 'skin.plextuaryce')]),
            'skin.plextuarycpm': ('4.0.0-pm4k1.15', world.newest[(DONT_PANIC, 'skin.plextuarycpm')]),
            'skin.p3i.estuary': ('8.8.25', world.newest[(P3I, 'skin.p3i.estuary')]),
        }
        expected = {
            'omega': dict(
                both,
                **{
                    'script.plexmod-uno': ('0.4.4', world.newest[(MAYBE_PANIC + 'zips/', 'script.plexmod-uno')]),
                    'skin.plextuary-uno': ('0.1.2', world.newest[(MAYBE_PANIC + 'zips/', 'skin.plextuary-uno')]),
                    'skin.plextuaryce-uno': ('0.1.3', world.newest[(MAYBE_PANIC + 'zips/', 'skin.plextuaryce-uno')]),
                    'skin.plextuarycpm-uno': ('0.1.3', world.newest[(MAYBE_PANIC + 'zips/', 'skin.plextuarycpm-uno')]),
                },
            ),
            'piers': dict(
                both,
                **{
                    'script.plexmod-uno': ('0.4.4', world.newest[(MAYBE_PANIC + 'piers/zips/', 'script.plexmod-uno')]),
                    'skin.plextuary-uno': ('22.0.1', world.newest[(MAYBE_PANIC + 'piers/zips/', 'skin.plextuary-uno')]),
                },
            ),
        }
        for feed, arch, platform in (('omega', 'arm', 'linux'), ('piers', 'aarch64', 'linux-aarch64')):
            for addon_id, (version, data) in expected[feed].items():
                entry = staged[(feed, addon_id)]
                self.assertEqual(entry['version'], version, (feed, addon_id))
                self.assertIsNone(entry['platform'])
                self.assertEqual((self.staging / entry['file']).read_bytes(), data, (feed, addon_id))
            coretube = staged[(feed, 'browser.tizentube')]
            self.assertEqual((coretube['version'], coretube['platform']), ('0.5.4', platform))
            self.assertEqual((self.staging / coretube['file']).read_bytes(), world.coretube[arch])
            listed = {addon_id for list_feed, addon_id in staged if list_feed == feed}
            self.assertEqual(listed, set(expected[feed]) | {'browser.tizentube'}, feed)

    def test_the_token_goes_only_to_the_github_api(self):
        self.collect(token='SECRET')

        for url, headers in self.world.web.requests:
            sent = 'Authorization' in headers
            self.assertEqual(sent, url.startswith('https://api.github.com/'), url)
        self.assertIn(
            ('Authorization', 'Bearer SECRET'),
            next(h for u, h in self.world.web.requests if u.startswith('https://api.github.com/')).items(),
        )

    def test_a_shared_zip_is_downloaded_once(self):
        self.collect()

        zips = [url for url, _ in self.world.web.requests if url.endswith('.zip')]
        self.assertEqual(len(zips), len(set(zips)))

    def test_a_project_without_a_release_is_left_out(self):
        del self.world.web.pages[f'{API}/somepanic/SM4K/releases/latest']

        self.collect()

        self.assertNotIn(('omega', 'script.silomod'), self.staged())
        self.assertIn(('omega', 'script.jellymod'), self.staged())

    def test_a_zip_that_fails_its_checksum_stops_the_run(self):
        url = 'https://github.com/somepanic/JM4K/releases/download/jellymod-v0.1.0/script.jellymod-0.1.0.zip'
        self.world.web.pages[url] = addon_zip('script.jellymod', '0.1.0', name='tampered')

        with self.assertRaisesRegex(collect.CollectError, 'script.jellymod-0.1.0.zip'):
            self.collect()

    def test_a_release_without_checksums_stops_the_run(self):
        latest = f'{API}/somepanic/JM4K/releases/latest'
        answer = json.loads(self.world.web.pages[latest])
        answer['assets'] = [a for a in answer['assets'] if a['name'] != 'SHA256SUMS']
        self.world.web.pages[latest] = json.dumps(answer).encode()

        with self.assertRaisesRegex(collect.CollectError, 'SHA256SUMS'):
            self.collect()

    def test_a_coretube_zip_for_the_wrong_architecture_stops_the_run(self):
        swapped = {'arm': self.world.coretube['aarch64'], 'aarch64': self.world.coretube['arm']}
        release(
            self.world.web,
            'somepanic/CoreTube',
            'v0.5.4',
            {f'browser.tizentube-0.5.4-{arch}.zip': data for arch, data in swapped.items()},
        )

        with self.assertRaisesRegex(collect.CollectError, 'architecture'):
            self.collect()

    def test_a_feed_that_fails_its_md5_stops_the_run(self):
        self.world.web.pages[DONT_PANIC + 'addons.xml.md5'] = b'0' * 32

        with self.assertRaisesRegex(collect.CollectError, 'md5'):
            self.collect()

    def test_a_zip_whose_addon_xml_disagrees_stops_the_run(self):
        self.world.web.pages[DONT_PANIC + 'script.plexmod/script.plexmod-1.3.19.zip'] = addon_zip(
            'script.plexmod', '1.3.18'
        )

        with self.assertRaisesRegex(collect.CollectError, '1.3.18'):
            self.collect()

    def test_staging_starts_empty(self):
        self.staging.mkdir()

        with self.assertRaises(FileExistsError):
            self.collect()
