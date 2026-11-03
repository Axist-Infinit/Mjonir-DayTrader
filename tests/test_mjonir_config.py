"""mjonir.config: the env layers, the key names, redaction by name and by value, ro_connect."""

import os
import sqlite3
import tempfile
import unittest

import _mj  # noqa: F401  (puts mjonir on sys.path)
from mjonir import config as C


class Layers(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.infinit = os.path.join(self.d, "infinit")
        self.repo = os.path.join(self.d, "repo")
        os.makedirs(self.infinit)
        os.makedirs(self.repo)

    def write(self, folder, text):
        with open(os.path.join(folder, ".env"), "w") as fh:
            fh.write(text)

    def test_later_layers_win(self):
        self.write(self.infinit, "# a comment\nMASSIVE_API_KEY=from-infinit-0001\nOTHER='quoted'\n\nNOEQUALS\n")
        self.write(self.repo, 'MASSIVE_BASE_URL="https://example.test/"\n')
        env = {"INFINIT_ROOT": self.infinit}
        layers = C.env_layers(self.repo, env)
        self.assertEqual(layers["MASSIVE_API_KEY"], "from-infinit-0001")
        self.assertEqual(layers["OTHER"], "quoted")
        self.assertNotIn("NOEQUALS", layers)
        self.assertEqual(C.api_base_url(layers), "https://example.test")
        self.write(self.repo, "MASSIVE_API_KEY=from-repo-00002\n")
        self.assertEqual(C.api_key(C.env_layers(self.repo, env)), "from-repo-00002")
        env["MASSIVE_API_KEY"] = "from-process-03"
        self.assertEqual(C.api_key(C.env_layers(self.repo, env)), "from-process-03")
        env["MASSIVE_API_KEY"] = ""          # an empty variable is not a layer
        self.assertEqual(C.api_key(C.env_layers(self.repo, env)), "from-repo-00002")

    def test_key_names_in_order(self):
        self.assertEqual(C.KEY_NAMES, ("MJONIR_API_KEY", "MASSIVE_API_KEY", "POLYGON_API_KEY", "POLYGONIO_API_KEY"))
        layers = {"POLYGON_API_KEY": "poly-000000000", "MJONIR_API_KEY": "mjonir-0000000"}
        self.assertEqual(C.api_key(layers), "mjonir-0000000")
        self.assertIsNone(C.api_key({}))
        self.assertEqual(C.api_base_url({}), "https://api.massive.com")

    def test_infinit_root_from_the_repo_layer(self):
        other = os.path.join(self.d, "elsewhere")
        os.makedirs(other)
        self.write(other, "POLYGON_API_KEY=elsewhere-00001\n")
        self.write(self.repo, "INFINIT_ROOT=%s\n" % other)
        self.assertEqual(C.api_key(C.env_layers(self.repo, {})), "elsewhere-00001")

    def test_an_unreadable_layer_is_empty(self):
        self.assertEqual(C._parse_env_file(os.path.join(self.d, "missing", ".env")), {})

    def test_key_like_values_names_only(self):
        self.write(self.repo, "MASSIVE_API_KEY=abcdefgh12345678\nSHORT_KEY=abc\nPLAIN=hello-world-long\n")
        names = C.key_like_values(os.path.join(self.repo, ".env"))
        self.assertEqual(names, ["MASSIVE_API_KEY"])

    def test_config_value(self):
        cfg = {"universe": {"min_price": 7}, "universe.min_adv_usd": 1}
        self.assertEqual(C.config_value(cfg, "universe.min_price", 5), 7)
        self.assertEqual(C.config_value(cfg, "universe.min_adv_usd", 9), 1)
        self.assertEqual(C.config_value({}, "universe.min_price", 5), 5)


class Redaction(unittest.TestCase):
    KEY = _mj.FAKE_KEY

    def test_by_name_and_by_value(self):
        text = ("GET https://api.massive.com/v2/x?apiKey=%s&limit=1 failed; header Bearer %s; again %s"
                % (self.KEY, self.KEY, self.KEY))
        out = C.redact(text, self.KEY)
        self.assertFalse(self.KEY in out)
        self.assertIn("apiKey=<redacted>&limit=1", out)
        self.assertIn("Bearer <redacted>", out)
        # by name even when the value is unknown (or too short to scrub by value)
        self.assertEqual(C.redact("x?apiKey=zz&y=1", None), "x?apiKey=<redacted>&y=1")
        self.assertEqual(C.redact("api_key=short'", "short"), "api_key=<redacted>'")
        self.assertEqual(C.redact("a short word", "short"), "a short word")   # under 8 characters: not a pattern


class ReadOnly(unittest.TestCase):
    def test_ro_connect_refuses_writes(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "store.sqlite3")
        conn = sqlite3.connect(p)
        conn.execute("CREATE TABLE t(a)")
        conn.commit()
        conn.close()
        ro = C.ro_connect(p)
        self.assertEqual(ro.execute("PRAGMA query_only").fetchone()[0], 1)
        with self.assertRaises(sqlite3.OperationalError):
            ro.execute("INSERT INTO t VALUES (1)")
        ro.close()
        with self.assertRaises(FileNotFoundError):
            C.ro_connect(os.path.join(d, "missing.sqlite3"))

    def test_data_dir_is_cwd_relative_unless_set(self):
        old = os.environ.pop("MJONIR_DATA_DIR")
        try:
            self.assertEqual(str(C.data_dir()), os.path.join(os.getcwd(), "trader", "data"))
        finally:
            os.environ["MJONIR_DATA_DIR"] = old
        self.assertEqual(str(C.data_dir()), old)


if __name__ == "__main__":
    unittest.main()
