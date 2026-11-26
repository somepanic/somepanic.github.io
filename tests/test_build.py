# SPDX-License-Identifier: BSD-3-Clause
"""
tools/build_site.py: the site Kodi reads, from the staged zips. One feed per Kodi version, each with its addons.xml and
sha256, the zips and their sha256 under <id>/, the add-ons' artwork beside them, and the repository add-on; the
repository add-on's zip and a page at the top.
"""

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import build_site as build

from .helpers import REPO, addon_zip, elf, sha256

REPOSITORY_ZIP = 'repository.somepanic-1.0.0.zip'


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.staging = Path(self.tmp.name) / 'staging'
        self.site = Path(self.tmp.name) / 'site'
        self.zips = {
            'script.silomod': addon_zip('script.silomod', '0.1.0', name='SiloMod (SM4K)'),
            'script.plexmod': addon_zip('script.plexmod', '1.3.19', assets=(), extra={'icon.png': b'old icon'}),
            'arm': addon_zip(
                'browser.tizentube', '0.5.4', path='obsolete/package.zip', extra={'cobalt/cobalt': elf(1, 40)}
            ),
            'aarch64': addon_zip('browser.tizentube', '0.5.4', extra={'cobalt/cobalt': elf(2, 183)}),
        }
        self.manifest = []
        for feed, arch, platform in (('omega', 'arm', 'linux'), ('piers', 'aarch64', 'linux-aarch64')):
            self.stage(feed, 'script.silomod', '0.1.0', self.zips['script.silomod'])
            self.stage(feed, 'script.plexmod', '1.3.19', self.zips['script.plexmod'])
            self.stage(feed, 'browser.tizentube', '0.5.4', self.zips[arch], platform)

    def stage(self, feed, addon_id, version, data, platform=None):
        name = f'{feed}/{addon_id}-{version}.zip'
        (self.staging / feed).mkdir(parents=True, exist_ok=True)
        (self.staging / name).write_bytes(data)
        self.manifest.append(
            {'feed': feed, 'id': addon_id, 'version': version, 'file': name, 'platform': platform, 'origin': 'test'}
        )

    def build(self):
        (self.staging / 'manifest.json').write_text(json.dumps(self.manifest))
        build.build(self.staging, self.site)

    def feed(self, name):
        data = (self.site / name / 'addons.xml').read_bytes()
        return data, {addon.get('id'): addon for addon in ET.fromstring(data).findall('addon')}

    def test_each_feed_lists_its_addons_and_the_repository(self):
        self.build()

        for feed, arch, platform in (('omega', 'arm', 'linux'), ('piers', 'aarch64', 'linux-aarch64')):
            data, addons = self.feed(feed)
            self.assertEqual(
                (self.site / feed / 'addons.xml.sha256').read_text().split()[0], hashlib.sha256(data).hexdigest()
            )
            self.assertEqual(
                sorted(addons), ['browser.tizentube', 'repository.somepanic', 'script.plexmod', 'script.silomod']
            )
            self.assertEqual(addons['script.silomod'].get('version'), '0.1.0')
            metadata = addons['browser.tizentube'].find("extension[@point='xbmc.addon.metadata']")
            self.assertEqual(metadata.findtext('platform'), platform)
            self.assertIsNone(metadata.find('path'))  # Kodi would fetch the zip from there, not <id>/<id>-<version>.zip
            silomod = addons['script.silomod'].find("extension[@point='xbmc.addon.metadata']")
            self.assertEqual(silomod.findtext('platform'), 'all')

            coretube = self.site / feed / 'browser.tizentube' / 'browser.tizentube-0.5.4.zip'
            self.assertEqual(coretube.read_bytes(), self.zips[arch])
            self.assertEqual(Path(str(coretube) + '.sha256').read_text().split()[0], sha256(self.zips[arch]))

    def test_artwork_sits_beside_the_zips(self):
        self.build()

        icon = self.site / 'omega' / 'script.silomod' / 'resources' / 'icon.png'
        self.assertEqual(icon.read_bytes(), b'art of script.silomod resources/icon.png')
        # an add-on without <assets>: Kodi looks for icon.png at its top
        self.assertEqual((self.site / 'piers' / 'script.plexmod' / 'icon.png').read_bytes(), b'old icon')

    def test_the_repository_addon_installs_and_updates_itself(self):
        self.build()

        top = (self.site / REPOSITORY_ZIP).read_bytes()
        with zipfile.ZipFile(self.site / REPOSITORY_ZIP) as z:
            self.assertEqual(
                sorted(z.namelist()), ['repository.somepanic/addon.xml', 'repository.somepanic/resources/icon.png']
            )
            self.assertEqual(z.read('repository.somepanic/addon.xml'), (REPO / 'repository' / 'addon.xml').read_bytes())
        for feed in ('omega', 'piers'):
            copy = self.site / feed / 'repository.somepanic' / REPOSITORY_ZIP
            self.assertEqual(copy.read_bytes(), top)
            self.assertEqual(Path(str(copy) + '.sha256').read_text().split()[0], sha256(top))

    def test_the_same_input_builds_the_same_site(self):
        self.build()
        first = {p.relative_to(self.site): p.read_bytes() for p in self.site.rglob('*') if p.is_file()}
        self.site = Path(self.tmp.name) / 'again'

        self.build()

        again = {p.relative_to(self.site): p.read_bytes() for p in self.site.rglob('*') if p.is_file()}
        self.assertEqual(first, again)

    def test_the_page_links_the_repository_and_lists_each_feed(self):
        self.stage('omega', 'script.extra', '1.0.0', addon_zip('script.extra', '1.0.0'))

        self.build()

        page = (self.site / 'index.html').read_text()
        self.assertIn(f'href="{REPOSITORY_ZIP}"', page)
        self.assertIn('https://somepanic.github.io/', page)
        self.assertNotIn('{{', page)
        self.assertTrue((self.site / '.nojekyll').exists())

        rows = {
            re.sub(r'<[^>]+>', ' ', row).split()[0]: row
            for row in re.findall(r'<tr>(.*?)</tr>', page, re.DOTALL)
            if '<td' in row
        }
        silomod = rows['SiloMod']
        self.assertIn('href="https://github.com/somepanic/SM4K"', silomod)
        self.assertIn('Browse and play your Silo server.', silomod)
        self.assertEqual(re.findall(r'<td class="version">(.*?)</td>', silomod), ['0.1.0', '0.1.0'])
        # an add-on outside repository/addons.json still shows, with the name and summary in its addon.xml
        self.assertIn('script.extra summary', rows['script.extra'])

    def test_kodi_lists_only_the_repository_zip_from_the_page(self):
        # Kodi's HTTP source lists a link only when its text is the file name: just the repository zip
        self.build()

        page = (self.site / 'index.html').read_text()
        links = re.findall(r'<a href="([^"]*)"[^>]*>\s*(.*?)\s*</a>', page, re.DOTALL)
        self.assertGreater(len(links), 3)
        self.assertEqual([href for href, text in links if href == text], [REPOSITORY_ZIP])

    def test_a_list_without_the_addon_says_so(self):
        self.manifest = [e for e in self.manifest if not (e['feed'] == 'piers' and e['id'] == 'script.silomod')]

        self.build()

        page = (self.site / 'index.html').read_text()
        silomod = next(row for row in re.findall(r'<tr>(.*?)</tr>', page, re.DOTALL) if 'SiloMod' in row)
        cells = re.findall(r'<td class="version">(.*?)</td>', silomod, re.DOTALL)
        self.assertEqual(cells[0], '0.1.0')
        self.assertIn('not in this list', cells[1])

    def test_a_zip_that_disagrees_with_the_manifest_stops_the_build(self):
        self.manifest[0]['version'] = '0.1.1'

        with self.assertRaisesRegex(build.BuildError, '0.1.1'):
            self.build()

    def test_an_addon_twice_in_a_feed_stops_the_build(self):
        self.stage('omega', 'script.silomod', '0.1.0', self.zips['script.silomod'])

        with self.assertRaisesRegex(build.BuildError, 'script.silomod'):
            self.build()

    def test_artwork_outside_the_addon_stops_the_build(self):
        self.manifest = []
        self.stage('omega', 'script.evil', '1.0.0', addon_zip('script.evil', '1.0.0', assets=('../../index.html',)))

        with self.assertRaisesRegex(build.BuildError, 'index.html'):
            self.build()

    def test_each_list_takes_only_skins_its_kodi_can_load(self):
        # Kodi 21's skin engine is xbmc.gui 5.17.0; Kodi 22's is 5.18.0 and still loads 5.17.0 skins
        self.stage('piers', 'skin.for21', '1.0.0', addon_zip('skin.for21', '1.0.0', gui='5.17.0'))
        self.stage('omega', 'skin.for22', '22.0.0', addon_zip('skin.for22', '22.0.0', gui='5.18.0'))

        with self.assertRaisesRegex(build.BuildError, r'omega: skin\.for22 needs xbmc\.gui 5\.18\.0'):
            self.build()

        self.manifest = [entry for entry in self.manifest if entry['id'] != 'skin.for22']
        self.site = Path(self.tmp.name) / 'second'
        self.build()
        self.assertIn('skin.for21', self.feed('piers')[1])

    def test_the_site_starts_empty(self):
        self.site.mkdir()

        with self.assertRaises(FileExistsError):
            self.build()

    def test_the_command_reports_a_failure_in_one_line(self):
        self.manifest[0]['version'] = '0.1.1'
        (self.staging / 'manifest.json').write_text(json.dumps(self.manifest))

        result = subprocess.run(
            [sys.executable, str(REPO / 'tools' / 'build_site.py'), str(self.staging), str(self.site)],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn('0.1.1', result.stderr)
        self.assertNotIn('Traceback', result.stderr)
