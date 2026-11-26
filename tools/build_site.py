# SPDX-License-Identifier: BSD-3-Clause
"""
Build the somepanic Kodi repository's site from the zips tools/collect_zips.py staged:

    python3 tools/build_site.py STAGING SITE

SITE (new) gets the repository add-on's zip and index.html at the top, and one folder per feed (Kodi version) with
addons.xml and addons.xml.sha256, and per add-on <id>/<id>-<version>.zip, its .sha256 and its artwork. GitHub Pages
serves SITE as https://somepanic.github.io/.
"""

import argparse
import hashlib
import html
import io
import json
import posixpath
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kodirepo import FEEDS, SKIN_ENGINES, AddonError, compare_versions, read_addon

SOURCE = Path(__file__).resolve().parent.parent / 'repository'
REPOSITORY_ID = 'repository.somepanic'
FEED_NAMES = {'omega': 'Kodi 21, CoreELEC 21 (32-bit ARM)', 'piers': 'Kodi 22, CoreELEC 22 (64-bit AArch64)'}
# what an add-on without <assets> shows (Kodi's defaults before <assets>)
LEGACY_ART = ('icon.png', 'fanart.jpg')


class BuildError(Exception):
    pass


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def write_with_sha256(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    Path(str(path) + '.sha256').write_text(sha256(data) + '\n')


def repository_zip(addon_xml, icon):
    """The repository add-on's zip, the same bytes on every build (fixed dates)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in ((f'{REPOSITORY_ID}/addon.xml', addon_xml), (f'{REPOSITORY_ID}/resources/icon.png', icon)):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return buffer.getvalue()


def artwork(addon):
    """The files Kodi shows for an add-on before installing it: its <assets>, or Kodi's old defaults."""
    metadata = addon.find("extension[@point='xbmc.addon.metadata']")
    assets = metadata.find('assets') if metadata is not None else None
    if assets is None:
        return list(LEGACY_ART), False
    return [element.text.strip() for element in assets if element.text and element.text.strip()], True


def safe_path(addon_id, path):
    normal = posixpath.normpath(path)
    if normal == '..' or normal.startswith(('/', '../')):
        raise BuildError(f'{addon_id}: its artwork {path} is outside the add-on')
    return normal


def add_addon(entry, data, feed_dir):
    """Place one staged add-on in its feed, and return its addons.xml entry."""
    addon_id = entry['id']
    try:
        addon = read_addon(data, addon_id, entry['version'], entry['file'])
    except AddonError as error:
        raise BuildError(str(error)) from error
    feed = feed_dir.name
    for need in addon.iter('import'):
        if need.get('addon') == 'xbmc.gui':
            oldest, newest = SKIN_ENGINES[feed]
            version = need.get('version') or '0'
            if compare_versions(version, oldest) < 0 or compare_versions(version, newest) > 0:
                raise BuildError(
                    f'{feed}: {addon_id} needs xbmc.gui {version}, and Kodi there loads {oldest} to {newest}'
                )
    metadata = addon.find("extension[@point='xbmc.addon.metadata']")
    if metadata is not None:
        for path in metadata.findall('path'):  # Kodi would fetch the zip from there, not from <id>/<id>-<version>.zip
            metadata.remove(path)
        if entry.get('platform'):
            platform = metadata.find('platform')
            if platform is None:
                platform = ET.SubElement(metadata, 'platform')
            platform.text = entry['platform']

    folder = feed_dir / addon_id
    write_with_sha256(folder / f'{addon_id}-{entry["version"]}.zip', data)
    paths, listed = artwork(addon)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = set(archive.namelist())
        for path in paths:
            normal = safe_path(addon_id, path)
            member = f'{addon_id}/{normal}'
            if member in names:
                (folder / normal).parent.mkdir(parents=True, exist_ok=True)
                (folder / normal).write_bytes(archive.read(member))
            elif listed:
                print(f'{feed_dir.name}: {addon_id} lists {path}, which its zip lacks')
    return addon


def page(repository_zip_name, listing):
    sections = []
    for feed in FEEDS:
        items = ''.join(
            f'\n          <li>{html.escape(name)} {html.escape(version)}</li>' for name, version in listing[feed]
        )
        sections.append(f'        <h3>{html.escape(FEED_NAMES[feed])}</h3>\n        <ul>{items}\n        </ul>')
    template = (SOURCE / 'index.html').read_text(encoding='utf-8')
    return template.replace('{{repository_zip}}', html.escape(repository_zip_name)).replace(
        '{{feeds}}', '\n'.join(sections)
    )


def build(staging, site):
    staging, site = Path(staging), Path(site)
    manifest = json.loads((staging / 'manifest.json').read_text(encoding='utf-8'))
    addon_xml = (SOURCE / 'addon.xml').read_bytes()
    repository = ET.fromstring(addon_xml)
    repository_name = f'{REPOSITORY_ID}-{repository.get("version")}.zip'
    repository_data = repository_zip(addon_xml, (SOURCE / 'resources' / 'icon.png').read_bytes())

    site.mkdir(parents=True, exist_ok=False)
    (site / repository_name).write_bytes(repository_data)
    listing = {}
    for feed in FEEDS:
        feed_dir = site / feed
        entries = sorted((entry for entry in manifest if entry['feed'] == feed), key=lambda entry: entry['id'])
        ids = [entry['id'] for entry in entries]
        for addon_id in {addon_id for addon_id in ids if ids.count(addon_id) > 1}:
            raise BuildError(f'{feed}: {addon_id} is staged more than once')
        index = ET.Element('addons')
        listing[feed] = []
        for entry in entries:
            addon = add_addon(entry, (staging / entry['file']).read_bytes(), feed_dir)
            index.append(addon)
            listing[feed].append((addon.get('name') or entry['id'], entry['version']))
        index.append(ET.fromstring(addon_xml))
        write_with_sha256(feed_dir / REPOSITORY_ID / repository_name, repository_data)
        icon = feed_dir / REPOSITORY_ID / 'resources' / 'icon.png'
        icon.parent.mkdir(parents=True, exist_ok=True)
        icon.write_bytes((SOURCE / 'resources' / 'icon.png').read_bytes())
        write_with_sha256(feed_dir / 'addons.xml', ET.tostring(index, encoding='utf-8', xml_declaration=True))
        print(f'{feed}: {len(entries)} add-ons and {REPOSITORY_ID}')

    (site / 'index.html').write_text(page(repository_name, listing), encoding='utf-8')
    (site / '.nojekyll').touch()


def main():
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument('staging', type=Path, help='the folder tools/collect_zips.py filled')
    parser.add_argument('site', type=Path, help='new folder for the site')
    args = parser.parse_args()
    try:
        build(args.staging, args.site)
    except (BuildError, OSError, KeyError, ValueError, ET.ParseError) as error:
        parser.exit(1, f'build: {error}\n')


if __name__ == '__main__':
    main()
