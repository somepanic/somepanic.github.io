# SPDX-License-Identifier: BSD-3-Clause
"""Kodi's add-on version order (xbmc/addons/AddonVersion.cpp), which picks the newest version upstream."""

import unittest

from kodirepo import compare_versions, newest


class VersionOrderTest(unittest.TestCase):
    def assertOlder(self, older, newer):
        self.assertEqual(compare_versions(older, newer), -1, f'{older} < {newer}')
        self.assertEqual(compare_versions(newer, older), 1, f'{newer} > {older}')

    def test_numbers_compare_as_numbers(self):
        self.assertOlder('1.9', '1.10')
        self.assertOlder('0.7.9', '1.0.0')

    def test_dont_panics_versions(self):
        versions = ['1.0.5e', '0.7.9-rev4', '1.3.19', '1.0.6-rev1', '1.0.0', '1.0.5d']
        self.assertEqual(newest(versions), '1.3.19')
        self.assertOlder('1.0.5d', '1.0.5e')
        self.assertOlder('1.0.6', '1.0.6-rev1')

    def test_tilde_sorts_before_the_release(self):
        self.assertOlder('1.0.0~beta1', '1.0.0')
        self.assertOlder('1.0.0~beta1', '1.0.0~beta2')

    def test_anything_after_the_numbers_sorts_after(self):
        self.assertOlder('1.0.0', '1.0.0+git1')

    def test_epoch_comes_first(self):
        self.assertOlder('2.0', '1:0.1')

    def test_letters_ignore_case(self):
        self.assertEqual(compare_versions('1.0A', '1.0a'), 0)

    def test_an_invalid_version_counts_as_0_0_0(self):
        self.assertOlder('1.0!', '0.1')
        self.assertEqual(compare_versions('', '0.0.0'), 0)
