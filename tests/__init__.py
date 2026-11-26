# SPDX-License-Identifier: BSD-3-Clause
"""The tools' tests. Run from the top of the repository: python3 -m unittest discover -s tests -t . -b"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tools'))
