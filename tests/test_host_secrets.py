"""Tests for plugins/filter/host_secrets.py: where a host's secrets come
from when its network has an OpenBao host.

    .venv/bin/python -m unittest discover -s tests
"""

import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "host_secrets", ROOT / "plugins" / "filter" / "host_secrets.py")
hs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hs)

FILE = {"GITEA_ADMIN_USER": "me", "GITEA_ADMIN_PASSWORD": "hunter22", "GITEA_ADMIN_EMAIL": "me@example.com"}
STORE = dict(FILE)


def decide(file_values=None, store_values=None, push=False):
    return hs.host_secrets_decide(file_values if file_values is not None else {},
                                  store_values if store_values is not None else {},
                                  file_values is not None, store_values is not None, push)


class Diff(unittest.TestCase):
    def test_same(self):
        self.assertEqual(hs.host_secrets_diff(FILE, STORE), [])

    def test_changed_and_missing_keys_by_name_only(self):
        store = dict(STORE, GITEA_ADMIN_PASSWORD="other")
        del store["GITEA_ADMIN_EMAIL"]
        file = dict(FILE, EXTRA="1")
        self.assertEqual(hs.host_secrets_diff(file, store), ["EXTRA", "GITEA_ADMIN_EMAIL", "GITEA_ADMIN_PASSWORD"])

    def test_none_is_empty(self):
        self.assertEqual(hs.host_secrets_diff(None, None), [])
        self.assertEqual(hs.host_secrets_diff(FILE, None), sorted(FILE))


class Decide(unittest.TestCase):
    def test_neither(self):
        self.assertEqual(decide(), {"action": "missing", "source": "", "write": False, "differ": []})

    def test_store_only_is_read(self):
        self.assertEqual(decide(store_values=STORE),
                         {"action": "read", "source": "openbao", "write": False, "differ": []})

    def test_file_only_is_imported(self):
        self.assertEqual(decide(file_values=FILE),
                         {"action": "import", "source": "imported", "write": True, "differ": []})

    def test_file_only_with_push_is_still_an_import(self):
        self.assertEqual(decide(file_values=FILE, push=True)["action"], "import")

    def test_equal_reads_the_store(self):
        self.assertEqual(decide(FILE, STORE),
                         {"action": "read", "source": "openbao", "write": False, "differ": []})

    def test_equal_with_push_writes_nothing(self):
        self.assertFalse(decide(FILE, STORE, push=True)["write"])

    def test_different_is_a_conflict_naming_the_keys(self):
        store = dict(STORE, GITEA_ADMIN_PASSWORD="other")
        self.assertEqual(decide(FILE, store),
                         {"action": "conflict", "source": "", "write": False, "differ": ["GITEA_ADMIN_PASSWORD"]})

    def test_different_with_push_overwrites(self):
        store = dict(STORE, GITEA_ADMIN_PASSWORD="other")
        self.assertEqual(decide(FILE, store, push=True),
                         {"action": "push", "source": "pushed", "write": True, "differ": ["GITEA_ADMIN_PASSWORD"]})

    def test_a_key_only_in_the_file_is_a_difference(self):
        self.assertEqual(decide(dict(FILE, NEW="x"), STORE)["differ"], ["NEW"])

    def test_an_empty_file_is_still_a_file(self):
        # It is imported as it is; the host's own checks then report the
        # missing keys, as with a file today.
        self.assertEqual(decide(file_values={})["action"], "import")
        self.assertEqual(decide({}, STORE)["action"], "conflict")

    def test_no_values_in_the_result(self):
        for result in (decide(FILE, dict(STORE, GITEA_ADMIN_PASSWORD="other")),
                       decide(FILE, dict(STORE, GITEA_ADMIN_PASSWORD="other"), push=True)):
            self.assertNotIn("hunter22", repr(result))
            self.assertNotIn("other", repr(result))

    def test_registered(self):
        self.assertEqual(set(hs.FilterModule().filters()), {"host_secrets_diff", "host_secrets_decide"})


if __name__ == "__main__":
    unittest.main()
