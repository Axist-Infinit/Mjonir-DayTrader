"""Paths, the API key and the read-only contract with the sibling stores. Stdlib only.

The key: ``api_key()`` reads three layers, later wins: ``${INFINIT_ROOT:-/home/axis/Infinit}/.env``,
then ``<repo>/.env``, then the process environment, over the names in ``KEY_NAMES``. The key lives in
``~/Infinit/.env``; never create ``<repo>/.env`` with a key (a local plugin install copies gitignored
files into the plugin cache, see docs/reviews/chunk0.md). ``bridge status`` warns when it finds one.

Never print, echo or log the key. Every message that may carry a URL goes through ``redact`` (by
name, ``apiKey=...``, and by value).

The sibling stores (Kalex 5m, the Infinit flat files) are opened through ``ro_connect``:
``file:...?mode=ro`` plus ``PRAGMA query_only=1``. Mjonir is never their second writer.
"""

import json
import os
import re
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: Credential names, in resolution order (the same convention as ~/Infinit and ~/Odyssey).
KEY_NAMES = ("MJONIR_API_KEY", "MASSIVE_API_KEY", "POLYGON_API_KEY", "POLYGONIO_API_KEY")
DEFAULT_INFINIT_ROOT = "/home/axis/Infinit"
DEFAULT_BASE_URL = "https://api.massive.com"
DEFAULT_KALEX_5M = "/home/axis/Kalex/data/intraday/intraday_5m.sqlite3"
DEFAULT_FLATFILES = "/home/axis/Infinit/data/polygon/minute_flatfiles"
DEFAULT_CONFIG = os.path.join("trader", "config.json")

#: The shortest value ever used as a scrub pattern: replacing a 3-character string everywhere would
#: make unrelated text look redacted (the house rule).
MIN_SECRET_CHARS = 8
#: ``apiKey=<value>`` up to the first delimiter: & or the quote or space that ends a URL in a message.
_APIKEY_PARAM = re.compile(r"(?i)(apiKey|api_key)=[^&'\"\s]*")
_BEARER = re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._\-]+")
REDACTED = "<redacted>"


def _parse_env_file(path):
    """Minimal .env reader: KEY=VALUE, ignoring comments and blank lines (ported from Odyssey)."""
    out = {}
    try:
        text = Path(path).read_text()
    except OSError:
        # Missing, unreadable, or behind a home that is not ours: an empty layer, never a crash.
        return out
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def repo_env_path(repo=None):
    return Path(repo or REPO) / ".env"


def env_layers(repo=None, environ=None):
    """{name: value}: ``${INFINIT_ROOT}/.env``, then ``<repo>/.env``, then the process env (later wins)."""
    environ = os.environ if environ is None else environ
    own = _parse_env_file(repo_env_path(repo))
    root = environ.get("INFINIT_ROOT") or own.get("INFINIT_ROOT") or DEFAULT_INFINIT_ROOT
    merged = _parse_env_file(Path(root) / ".env")
    merged.update(own)
    merged.update({k: v for k, v in environ.items() if v})
    return merged


def env(name, default=None, layers=None):
    return (env_layers() if layers is None else layers).get(name, default)


def api_key(layers=None):
    """The first non-empty key name, or None. Never print what this returns."""
    layers = env_layers() if layers is None else layers
    for name in KEY_NAMES:
        v = layers.get(name)
        if v:
            return v
    return None


def api_base_url(layers=None):
    return (env("MASSIVE_BASE_URL", None, layers) or DEFAULT_BASE_URL).rstrip("/")


def data_dir():
    """``${MJONIR_DATA_DIR:-<cwd>/trader/data}``: cwd-relative like every upstream script."""
    return Path(os.environ.get("MJONIR_DATA_DIR") or os.path.join(os.getcwd(), "trader", "data"))


def kalex_5m_path():
    return Path(os.environ.get("MJONIR_KALEX_5M") or DEFAULT_KALEX_5M)


def flatfile_dir():
    return Path(os.environ.get("MJONIR_FLATFILE_DIR") or DEFAULT_FLATFILES)


def trader_config(path=None):
    """trader/config.json as a dict ({} when absent). A broken file raises ValueError with its path."""
    p = path or os.environ.get("TRADER_CONFIG") or DEFAULT_CONFIG
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as fh:
        try:
            doc = json.load(fh)
        except ValueError as e:
            raise ValueError("%s is not valid JSON: %s" % (p, e))
    return doc if isinstance(doc, dict) else {}


def config_value(cfg, dotted, default):
    """``universe.min_price`` reads cfg["universe"]["min_price"] (or a flat "universe.min_price" key)."""
    if dotted in cfg:
        return cfg[dotted]
    cur = cfg
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def redact(text, key=None):
    """Text with the key removed TWICE: by name (``apiKey=...``, a Bearer token) and by value.

    By name catches a key too short or odd to match by value; by value catches an appearance that
    is not spelled ``apiKey=``. Either alone has failed somewhere before; both is the rule."""
    s = _APIKEY_PARAM.sub(lambda m: "%s=%s" % (m.group(1), REDACTED), str(text))
    s = _BEARER.sub(lambda m: m.group(1) + REDACTED, s)
    if key and len(key) >= MIN_SECRET_CHARS:
        s = s.replace(key, REDACTED)
    return s


def key_like_values(path):
    """Names in an env file whose value looks like a credential (for `bridge status`). Never the values."""
    out = []
    for k, v in _parse_env_file(path).items():
        if (k in KEY_NAMES or re.search(r"(KEY|SECRET|TOKEN|PASSWORD)", k.upper())) and len(v) >= MIN_SECRET_CHARS:
            out.append(k)
    return sorted(out)


def ro_connect(path):
    """Open a sibling store strictly read-only: ``mode=ro`` URI plus ``PRAGMA query_only``.

    ``mode=ro`` bars writes to the database; it does not stop SQLite creating a missing ``-shm``
    beside a WAL store whose directory is writable (Odyssey measured it). What is honoured, and
    tested, is that the database bytes never change and no write is accepted through this
    connection."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError("read-only store missing: %s" % p)
    conn = sqlite3.connect("file:%s?mode=ro" % p, uri=True)
    try:
        conn.execute("PRAGMA query_only=1")
        conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchall()
    except sqlite3.Error:
        conn.close()
        raise
    return conn
