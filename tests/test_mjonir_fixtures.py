"""The recorded Massive fixtures carry no credential: no 20+ character token mixing upper case, lower
case and digits (the shape of a Massive key), and not the configured key itself when one is set."""

import os
import re
import unittest

import _mj
from mjonir import config as C

TOKEN = re.compile(r"[A-Za-z0-9]{20,}")


def key_like(text):
    return [t for t in TOKEN.findall(text)
            if re.search(r"[A-Z]", t) and re.search(r"[a-z]", t) and re.search(r"[0-9]", t)]


class NoKeys(unittest.TestCase):
    def files(self):
        out = []
        for base, _, names in os.walk(_mj.MFIX):
            out += [os.path.join(base, n) for n in names]
        self.assertGreaterEqual(len(out), 9)
        return out

    def test_no_key_like_token_in_any_fixture(self):
        for p in self.files():
            with open(p, encoding="utf-8") as fh:
                found = key_like(fh.read())
            self.assertEqual(len(found), 0, "%s holds %d key-like token(s)" % (os.path.basename(p), len(found)))

    def test_the_detector_works(self):
        self.assertEqual(len(key_like('{"x": "%s"}' % _mj.FAKE_KEY)), 1)
        self.assertEqual(key_like("a1b2c3d4e5f6a7b8c9d0e1f2 BBG000C2V3D6 dbe378bac57c97e81b427f3232696f78"), [])

    def test_not_the_configured_key(self):
        key = C.api_key()
        if not key:
            self.skipTest("no key configured on this machine")
        for p in self.files():
            with open(p, encoding="utf-8") as fh:
                self.assertFalse(key in fh.read(), "the key is in %s" % os.path.basename(p))


if __name__ == "__main__":
    unittest.main()
