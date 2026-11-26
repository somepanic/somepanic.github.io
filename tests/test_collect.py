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


def release(web, repo, tag, files):
    """A GitHub release of repo with files (name: bytes) and their SHA256SUMS."""
    files = dict(files, SHA256SUMS=sums(files))
    base = f'https://github.com/{repo}/releases/download/{tag}/'
    assets = [{'name': name, 'browser_download_url': base + name} for name in files]
    web.pages[f'{API}/{repo}/releases/latest'] = json.dumps({'tag_name': tag, 'assets': assets}).encode()
    for name, data in files.items():
        web.pages[base + name] = data


def kodi_feed(web, base, addon_id, zips):
    """A Kodi repository feed at base listing zips (version: bytes) of addon_id, with addons.xml.md5."""
    root = ET.Element('addons')
    for version, data in zips.items():
        root.append(ET.fromstring(addon_xml(addon_id, version)))
        web.pages[f'{base}{addon_id}/{addon_id}-{version}.zip'] = data
    index = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    web.pages[base + 'addons.xml'] = index
    web.pages[base + 'addons.xml.md5'] = hashlib.md5(index).hexdigest().encode()


class World:
    """Every source with one release or feed, as they stand."""

    def __init__(self):
        self.web = FakeWeb({})
        self.silomod = addon_zip('script.silomod', '0.1.0', name='SiloMod (SM4K)')
        self.jellymod = addon_zip('script.jellymod', '0.1.0', name='JellyMod (JM4K)')
        self.coretube = {
            'arm': addon_zip('browser.tizentube', '0.5.4', extra={'cobalt/cobalt': elf(1, 40)}),
            'aarch64': addon_zip('browser.tizentube', '0.5.4', extra={'cobalt/cobalt': elf(2, 183)}),
        }
        self.plexmod = addon_zip('script.plexmod', '1.3.19')
        self.uno = addon_zip('script.plexmod-uno', '0.4.4')
        release(self.web, 'somepanic/SM4K', 'v0.1.0', {'script.silomod-0.1.0.zip': self.silomod})
        release(self.web, 'somepanic/JM4K', 'v0.1.0', {'script.jellymod-0.1.0.zip': self.jellymod})
        release(
            self.web,
            'somepanic/CoreTube',
            'v0.5.4',
            {f'browser.tizentube-0.5.4-{arch}.zip': data for arch, data in self.coretube.items()},
        )
        kodi_feed(
            self.web,
            DONT_PANIC,
            'script.plexmod',
            {'1.0.6-rev1': addon_zip('script.plexmod', '1.0.6-rev1'), '1.3.19': self.plexmod},
        )
        for feed in ('zips/', 'piers/zips/'):
            kodi_feed(
                self.web,
                MAYBE_PANIC + feed,
                'script.plexmod-uno',
                {'0.4.3': addon_zip('script.plexmod-uno', '0.4.3'), '0.4.4': self.uno},
            )


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

    def test_the_newest_of_every_addon_for_both_feeds(self):
        self.collect()

        staged = self.staged()
        expected = {
            'script.silomod': ('0.1.0', self.world.silomod),
            'script.jellymod': ('0.1.0', self.world.jellymod),
            'script.plexmod': ('1.3.19', self.world.plexmod),
            'script.plexmod-uno': ('0.4.4', self.world.uno),
        }
        for feed, arch, platform in (('omega', 'arm', 'linux'), ('piers', 'aarch64', 'linux-aarch64')):
            for addon_id, (version, data) in expected.items():
                entry = staged[(feed, addon_id)]
                self.assertEqual(entry['version'], version)
                self.assertIsNone(entry['platform'])
                self.assertEqual((self.staging / entry['file']).read_bytes(), data)
            coretube = staged[(feed, 'browser.tizentube')]
            self.assertEqual((coretube['version'], coretube['platform']), ('0.5.4', platform))
            self.assertEqual((self.staging / coretube['file']).read_bytes(), self.world.coretube[arch])
        self.assertEqual(len(staged), 10)

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
        url = 'https://github.com/somepanic/JM4K/releases/download/v0.1.0/script.jellymod-0.1.0.zip'
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
