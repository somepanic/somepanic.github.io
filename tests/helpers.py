# SPDX-License-Identifier: BSD-3-Clause
"""Fake add-on zips, checksums and a fake web for the tools' tests."""

import hashlib
import io
import struct
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import collect_zips

REPO = Path(__file__).resolve().parent.parent


def addon_xml(addon_id, version, name=None, platform='all', assets=('resources/icon.png',), path=None):
    root = ET.Element('addon', {'id': addon_id, 'name': name or addon_id, 'version': version, 'provider-name': 'test'})
    requires = ET.SubElement(root, 'requires')
    ET.SubElement(requires, 'import', addon='xbmc.python', version='3.0.0')
    ET.SubElement(root, 'extension', point='xbmc.python.script', library='default.py')
    metadata = ET.SubElement(root, 'extension', point='xbmc.addon.metadata')
    ET.SubElement(metadata, 'summary').text = f'{addon_id} summary'
    ET.SubElement(metadata, 'platform').text = platform
    if assets:
        art = ET.SubElement(metadata, 'assets')
        for asset in assets:
            ET.SubElement(art, 'fanart' if asset.endswith('.jpg') else 'icon').text = asset
    if path:
        ET.SubElement(metadata, 'path').text = path
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def addon_zip(addon_id, version, name=None, platform='all', assets=('resources/icon.png',), extra=None, path=None):
    """An add-on zip as Kodi expects it: one top folder named after the add-on."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as z:
        z.writestr(f'{addon_id}/addon.xml', addon_xml(addon_id, version, name, platform, assets, path))
        for asset in assets:
            z.writestr(f'{addon_id}/{asset}', f'art of {addon_id} {asset}'.encode())
        for name_in_zip, data in (extra or {}).items():
            z.writestr(f'{addon_id}/{name_in_zip}', data)
    return buffer.getvalue()


def elf(bits, machine):
    """The start of an ELF executable: class 1 (32-bit) or 2 (64-bit), machine 40 (ARM) or 183 (AArch64)."""
    header = bytearray(64)
    header[:6] = b'\x7fELF' + bytes([bits, 1])
    struct.pack_into('<H', header, 18, machine)
    return bytes(header)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def sums(files):
    return ''.join(f'{sha256(data)}  {name}\n' for name, data in files.items()).encode()


class FakeWeb:
    """collect_zips.fetch's stand-in: the pages it knows, NotFound for the rest, and every request it got."""

    def __init__(self, pages):
        self.pages = dict(pages)
        self.requests = []

    def __call__(self, url, headers=None):
        self.requests.append((url, dict(headers or {})))
        if url not in self.pages:
            raise collect_zips.NotFound(url)
        return self.pages[url]
