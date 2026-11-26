# SPDX-License-Identifier: BSD-3-Clause
"""
Collect the newest zip of every add-on the somepanic repository publishes, checked, for each feed:

    python3 tools/collect_zips.py STAGING

Our own add-ons come from their latest GitHub release (a zip, or one per architecture, and SHA256SUMS). PlexMod for
Kodi (PM4K) and Plex Uno come unchanged from the Kodi repositories their authors publish (Don't Panic, Maybe Panic),
checked against those feeds' addons.xml.md5. STAGING (new) gets the zips and manifest.json, which tools/build_site.py reads.
With GITHUB_TOKEN set, it goes to GitHub's API, and nowhere else.
"""

import argparse
import hashlib
import io
import json
import os
import re
import struct
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kodirepo import FEEDS, AddonError, newest, read_addon

API = 'https://api.github.com'
USER_AGENT = 'somepanic-kodi-repository'
DONT_PANIC = 'https://raw.githubusercontent.com/pannal/dontpanickodi/master/omega/zips/'  # Kodi 20.90 and newer
MAYBE_PANIC = 'https://raw.githubusercontent.com/FilHarr/maybepanic/main/'

# per feed: the architecture a per-architecture release ships for it, its launcher's ELF class and machine
# (ARM 40, AArch64 183), and the platform Kodi knows it by (CoreELEC 21's 32-bit Kodi has no linux-armv7)
ARCHITECTURES = {'omega': ('arm', 1, 40, 'linux'), 'piers': ('aarch64', 2, 183, 'linux-aarch64')}

SOURCES = (
    {'id': 'script.silomod', 'release': 'somepanic/SM4K'},
    {'id': 'script.jellymod', 'release': 'somepanic/JM4K'},
    {'id': 'browser.tizentube', 'release': 'somepanic/CoreTube', 'launcher': 'cobalt/cobalt'},
    {'id': 'script.plexmod', 'feeds': {'omega': DONT_PANIC, 'piers': DONT_PANIC}},
    {'id': 'script.plexmod-uno', 'feeds': {'omega': MAYBE_PANIC + 'zips/', 'piers': MAYBE_PANIC + 'piers/zips/'}},
)


class CollectError(Exception):
    pass


class NotFound(CollectError):
    pass


def fetch(url, headers=None):
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        if error.code == 404:
            raise NotFound(url) from error
        raise CollectError(f'{url}: HTTP {error.code}') from error
    except urllib.error.URLError as error:
        raise CollectError(f'{url}: {error.reason}') from error


class Downloads:
    """fetch, once per URL: a zip both feeds share is downloaded one time."""

    def __init__(self, fetch):
        self.fetch = fetch
        self.cache = {}

    def get(self, url):
        if url not in self.cache:
            self.cache[url] = self.fetch(url)
        return self.cache[url]


def check_launcher(data, source, feed, name):
    _, bits, machine, _ = ARCHITECTURES[feed]
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        header = archive.read(f'{source["id"]}/{source["launcher"]}')[:20]
    if (
        len(header) < 20
        or header[:6] != b'\x7fELF' + bytes([bits, 1])
        or struct.unpack_from('<H', header, 18)[0] != machine
    ):
        raise CollectError(f'{name}: its {source["launcher"]} is not built for the {feed} architecture')


def from_release(source, downloads, token):
    """{feed: (version, zip bytes, platform, origin)} from source's latest GitHub release, or {} without one."""
    headers = {'Accept': 'application/vnd.github+json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    try:
        release = json.loads(downloads.fetch(f'{API}/repos/{source["release"]}/releases/latest', headers))
    except NotFound:
        print(f'{source["id"]}: {source["release"]} has no release yet, left out')
        return {}
    tag = release.get('tag_name')
    assets = {asset['name']: asset['browser_download_url'] for asset in release.get('assets', [])}
    if 'SHA256SUMS' not in assets:
        raise CollectError(f'{source["release"]} {tag}: no SHA256SUMS among its files')
    checksums = {}
    for line in downloads.get(assets['SHA256SUMS']).decode('utf-8').splitlines():
        if line.strip():
            digest, name = line.split(maxsplit=1)
            checksums[name.lstrip('*')] = digest.lower()

    found = {}
    for feed in FEEDS:
        suffix = f'-{ARCHITECTURES[feed][0]}' if 'launcher' in source else ''
        pattern = re.compile(re.escape(source['id']) + r'-(.+)' + re.escape(suffix) + r'\.zip')
        names = [(name, match.group(1)) for name in assets if (match := pattern.fullmatch(name))]
        if 'launcher' not in source:
            names = [(name, version) for name, version in names if not version.endswith(('-arm', '-aarch64'))]
        if len(names) != 1:
            raise CollectError(
                f'{source["release"]} {tag}: expected one {source["id"]}-<version>{suffix}.zip, found {len(names)}'
            )
        name, version = names[0]
        data = downloads.get(assets[name])
        if hashlib.sha256(data).hexdigest() != checksums.get(name):
            raise CollectError(f'{source["release"]} {tag}: {name} does not match its SHA256SUMS line')
        read_addon(data, source['id'], version, name)
        platform = None
        if 'launcher' in source:
            check_launcher(data, source, feed, name)
            platform = ARCHITECTURES[feed][3]
        found[feed] = (version, data, platform, assets[name])
    return found


def from_feeds(source, downloads):
    """{feed: (version, zip bytes, None, origin)}: the newest source['id'] in each upstream Kodi feed."""
    found = {}
    for feed in FEEDS:
        base = source['feeds'][feed]
        index = downloads.get(base + 'addons.xml')
        expected = downloads.get(base + 'addons.xml.md5').decode('ascii', 'replace').split()
        if not expected or hashlib.md5(index).hexdigest() != expected[0].lower():
            raise CollectError(f'{base}addons.xml does not match its addons.xml.md5')
        versions = [
            addon.get('version') for addon in ET.fromstring(index).findall('addon') if addon.get('id') == source['id']
        ]
        if not versions:
            raise CollectError(f'{base}addons.xml does not list {source["id"]}')
        version = newest(versions)
        url = f'{base}{source["id"]}/{source["id"]}-{version}.zip'
        data = downloads.get(url)
        read_addon(data, source['id'], version, url)
        found[feed] = (version, data, None, url)
    return found


def collect(staging, sources=SOURCES, fetch=fetch, token=None):
    """Stage every source's newest zip per feed into staging (which must not exist yet) and write manifest.json."""
    staging = Path(staging)
    downloads = Downloads(fetch)
    collected = []
    for source in sources:
        try:
            found = from_release(source, downloads, token) if 'release' in source else from_feeds(source, downloads)
        except AddonError as error:
            raise CollectError(str(error)) from error
        for feed, (version, data, platform, origin) in found.items():
            collected.append((feed, source['id'], version, data, platform, origin))

    staging.mkdir(parents=True, exist_ok=False)
    manifest = []
    for feed, addon_id, version, data, platform, origin in collected:
        name = f'{feed}/{addon_id}-{version}.zip'
        (staging / feed).mkdir(exist_ok=True)
        (staging / name).write_bytes(data)
        manifest.append(
            {'feed': feed, 'id': addon_id, 'version': version, 'file': name, 'platform': platform, 'origin': origin}
        )
        print(f'{feed}: {addon_id} {version}')
    (staging / 'manifest.json').write_text(json.dumps(manifest, indent=1) + '\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument('staging', type=Path, help='new folder for the zips and manifest.json')
    args = parser.parse_args()
    try:
        collect(args.staging, token=os.environ.get('GITHUB_TOKEN'))
    except (CollectError, OSError) as error:
        parser.exit(1, f'collect: {error}\n')


if __name__ == '__main__':
    main()
