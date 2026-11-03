"""Load a script from a skill folder (the folder names have hyphens)."""

import atexit
import hashlib
import importlib.util
import os
import shutil
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures")

# Hermetic: the suite runs from the repo root, where `mjonir.bridge calendar` writes trader/calendar.json
# and the owner may export TRADER_SOURCE=massive. Neither may reach a test that did not ask for it.
os.environ["TRADER_CALENDAR"] = os.devnull
os.environ.pop("TRADER_SOURCE", None)
# ...and no test ever finds the Massive key: no ~/Infinit/.env layer, no key in the process env. A code path
# a test forgot to serve then fails as "no key" (unverified) instead of calling the network.
# HIDDEN keeps what was hidden, for the one test that checks the key is in no fixture (never printed).
HIDDEN = {"INFINIT_ROOT": os.environ.get("INFINIT_ROOT")}
os.environ["INFINIT_ROOT"] = os.devnull
for _name in ("MJONIR_API_KEY", "MASSIVE_API_KEY", "POLYGON_API_KEY", "POLYGONIO_API_KEY"):
    HIDDEN[_name] = os.environ.pop(_name, None)


def record_snapshot():
    """{name: sha256} of every file in the repo's own record/ (tracked, append-only): no test may write it."""
    d = os.path.join(ROOT, "record")
    out = {}
    for name in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        with open(os.path.join(d, name), "rb") as fh:
            out[name] = hashlib.sha256(fh.read()).hexdigest()
    return out


# ...and no test ever writes the repo's forward record: entry.py --record (on by default), ticket.py approve and
# decline, and record.py all write ${TRADER_RECORD_DIR:-record}; the suite points it at a throwaway folder.
# RECORD_BEFORE is the repo's record/ when the first test module loaded (tests/test_zz_record_untouched.py, the
# last file discovered, compares it after the whole suite).
RECORD_BEFORE = record_snapshot()
RECORD_DIR = tempfile.mkdtemp(prefix="mjonir-record-tests-")
os.environ["TRADER_RECORD_DIR"] = RECORD_DIR
atexit.register(shutil.rmtree, RECORD_DIR, True)


def load(folder, name):
    path = os.path.join(ROOT, folder, name + ".py")
    spec = importlib.util.spec_from_file_location("trader_" + name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
