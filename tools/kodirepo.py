# SPDX-License-Identifier: BSD-3-Clause
"""What tools/collect_zips.py and tools/build_site.py share: the feeds, Kodi's version order and an add-on zip's addon.xml."""

import functools
import io
import xml.etree.ElementTree as ET
import zipfile

# One feed per Kodi version, named as Kodi's own mirrors name them: omega for Kodi 21 (CoreELEC 21, 32-bit ARM),
# piers for Kodi 22 and its 21.90+ pre-releases (CoreELEC 22, AArch64). repository/addon.xml sends each Kodi to its feed.
FEEDS = ('omega', 'piers')

# Per list, the skin engine (xbmc.gui) versions its Kodi loads, oldest first: addons/xbmc.gui/addon.xml in Kodi's
# sources says Kodi 21 is 5.17.0 (backwards-compatible to 5.17.0), Kodi 22 is 5.18.0 (backwards-compatible to 5.17.0).
SKIN_ENGINES = {'omega': ('5.17.0', '5.17.0'), 'piers': ('5.17.0', '5.18.0')}

# Kodi's version rules, from xbmc/addons/AddonVersion.cpp: [epoch:]upstream[-revision], letters in any case
VALID_CHARACTERS = frozenset('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.+_@~')
DIGITS = frozenset('0123456789')


class AddonError(Exception):
    """An add-on zip that isn't the add-on it should be."""


def _leading_number(text, start):
    """The number at text[start:] (0 when none) and where it ends, as C's strtol reads it."""
    end = start
    while end < len(text) and text[end] in DIGITS:
        end += 1
    return (int(text[start:end]) if end > start else 0), end


def _split(version):
    version = (version or '0.0.0').lower()
    epoch = 0
    if ':' in version:
        head, version = version.split(':', 1)
        epoch = _leading_number(head, 0)[0]
    revision = ''
    if '-' in version:
        version, revision = version.split('-', 1)
        if not set(revision) <= VALID_CHARACTERS:
            revision = ''
    if not set(version) <= VALID_CHARACTERS:
        version = '0.0.0'
    return epoch, version, revision


def _compare_component(a, b):
    """Kodi's CAddonVersion::CompareComponent: numbers compare as numbers, '~' sorts before anything."""
    i = j = 0
    while i < len(a) and j < len(b):
        while i < len(a) and j < len(b) and a[i] not in DIGITS and b[j] not in DIGITS:
            if a[i] != b[j]:
                if a[i] == '~':
                    return -1
                if b[j] == '~':
                    return 1
                return -1 if a[i] < b[j] else 1
            i += 1
            j += 1
        if i < len(a) and j < len(b) and (a[i] not in DIGITS or b[j] not in DIGITS):
            if a[i] == '~':
                return -1
            if b[j] == '~':
                return 1
            return -1 if a[i] in DIGITS else 1
        number_a, i = _leading_number(a, i)
        number_b, j = _leading_number(b, j)
        if number_a != number_b:
            return -1 if number_a < number_b else 1
    if i >= len(a) and j >= len(b):
        return 0
    if i < len(a):
        return -1 if a[i] == '~' else 1
    return 1 if b[j] == '~' else -1


def compare_versions(a, b):
    """-1, 0 or 1 as Kodi orders add-on versions a and b."""
    epoch_a, upstream_a, revision_a = _split(a)
    epoch_b, upstream_b, revision_b = _split(b)
    if epoch_a != epoch_b:
        return -1 if epoch_a < epoch_b else 1
    return _compare_component(upstream_a, upstream_b) or _compare_component(revision_a, revision_b)


def newest(versions):
    return max(versions, key=functools.cmp_to_key(compare_versions))


def read_addon(data, addon_id, version, where):
    """The addon.xml of an add-on zip (bytes), checked to be addon_id at version; where names the zip in errors."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            tops = {name.split('/', 1)[0] for name in archive.namelist()}
            if tops != {addon_id}:
                raise AddonError(f'{where}: holds {", ".join(sorted(tops))}, not one {addon_id} folder')
            root = ET.fromstring(archive.read(f'{addon_id}/addon.xml'))
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as error:
        raise AddonError(f'{where}: not an add-on zip ({error})') from error
    found = (root.get('id'), root.get('version'))
    if root.tag != 'addon' or found != (addon_id, version):
        raise AddonError(f'{where}: its addon.xml says {found[0]} {found[1]}, not {addon_id} {version}')
    return root
