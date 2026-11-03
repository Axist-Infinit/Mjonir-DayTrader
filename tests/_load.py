"""Load a script from a skill folder (the folder names have hyphens)."""

import importlib.util
import os

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


def load(folder, name):
    path = os.path.join(ROOT, folder, name + ".py")
    spec = importlib.util.spec_from_file_location("trader_" + name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
