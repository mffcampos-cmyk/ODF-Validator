"""Relocate pytest's temporary directories into the repository.

Why this exists
---------------
pytest builds its scratch directories under the system temp directory, at
``<tempdir>/pytest-of-<user>/``. If that directory survives with an ACL the
running account can no longer read -- which is what a Windows update left
behind here -- then ``os.scandir`` raises PermissionError inside pytest's own
``tmp_path`` factory, and EVERY test taking ``tmp_path`` errors during setup,
before its body runs. Hundreds of identical tracebacks, one cause, and nothing
to do with the code under test.

``PYTEST_DEBUG_TEMPROOT`` moves that whole tree into ``.pytest_tmp/`` beside
this file, which is created fresh and owned by whoever runs the suite, so the
stale-ACL failure cannot recur.

Why not --basetemp
------------------
``--basetemp`` would also relocate it, but pytest ``rm_rf``s that exact
directory at session start and then recreates it. On a mount where unlink is
refused -- the Linux sandbox this project is also developed in -- the removal
fails and the following ``mkdir`` raises FileExistsError during
``pytest_configure``, aborting the entire run rather than one test. It also
discards pytest's numbered-directory rotation, so two concurrent runs in one
checkout would delete each other's live fixtures.

``PYTEST_DEBUG_TEMPROOT`` keeps the ``pytest-of-<user>/pytest-N`` scheme, its
lock handling and its retention-based cleanup. Nothing is wiped wholesale.

Why the repository root
-----------------------
This must be read before the tmpdir plugin's ``pytest_configure`` builds the
factory. A root-level conftest.py is imported during initial conftest
collection, which happens first; ``tests/conftest.py`` is too late.
"""
from __future__ import annotations

import os
import pathlib

_TEMPROOT = pathlib.Path(__file__).parent / ".pytest_tmp"

# mkdir because pytest joins "pytest-of-<user>" onto this path and calls
# mkdir() without parents=True -- a missing temproot would be an OSError at
# startup. exist_ok so a second run is fine.
_TEMPROOT.mkdir(exist_ok=True)

# setdefault, not assignment: an explicit PYTEST_DEBUG_TEMPROOT in the
# environment, or a --basetemp on the command line, should still win. This is
# a better default, not a policy.
os.environ.setdefault("PYTEST_DEBUG_TEMPROOT", str(_TEMPROOT))
