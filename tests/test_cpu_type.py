"""Tests for VM CPU types (docs/plans/CPU-TYPE.md): cpu: on hosts,
vm_cpu_type, the inventory, and reading Proxmox's pending changes.

    .venv/bin/python -m unittest discover -s tests
"""

import copy
import unittest

from test_network_config import errors, load_networks, load_repo_networks, network_config as nc


def with_cpu(value, host_name=None):
    files = copy.deepcopy(load_networks())
    host = files[0]["config"]["hosts"][0] if host_name is None else next(
        h for f in files for h in f["config"]["hosts"] if h["name"] == host_name)
    host["cpu"] = value
    return files


class HostCpu(unittest.TestCase):
    def test_allowed(self):
        for value in ("x86-64-v2-AES", "x86-64-v2", "host"):
            self.assertEqual(errors(with_cpu(value)), [], value)

    def test_rejected(self):
        for value in ("kvm64", "qemu64", "Host", "", 64, None):
            found = errors(with_cpu(value))
            self.assertTrue(any("isn't an allowed CPU type" in e for e in found), (value, found))

    def test_needs_avx2(self):
        for value in ("x86-64-v3", "x86-64-v4"):
            found = errors(with_cpu(value))
            self.assertTrue(any("needs AVX2" in e for e in found), (value, found))

    def test_repo_networks_valid(self):
        self.assertEqual(errors(load_repo_networks()), [])


class DefaultCpu(unittest.TestCase):
    def test_default_checked(self):
        self.assertEqual(nc.network_config_cpu_type_errors("x86-64-v2-AES"), [])
        self.assertEqual(len(nc.network_config_cpu_type_errors("kvm64")), 1)
        self.assertIn("proxmox/vars.yaml", nc.network_config_cpu_type_errors("x86-64-v3")[0])


class Inventory(unittest.TestCase):
    def inventory(self, files):
        return nc.network_config_inventory({f["file"]: f["config"] for f in files})

    def test_empty_when_not_set(self):
        hosts = self.inventory(load_networks())["hosts"].values()
        self.assertTrue(all(h["cpu"] == "" for h in hosts))

    def test_host_value(self):
        files = with_cpu("host")
        first = files[0]
        hid = f"{first['file']}.{first['config']['hosts'][0]['name']}"
        self.assertEqual(self.inventory(files)["hosts"][hid]["cpu"], "host")


class PendingState(unittest.TestCase):
    """GET /nodes/<node>/qemu/<vmid>/pending returns every option with its
    value, plus pending (a change waiting for a restart) or delete."""

    def test_no_cpu_option(self):
        self.assertEqual(nc.proxmox_cpu_state([{"key": "memory", "value": 4096}]),
                         {"current": "kvm64", "next": "kvm64", "pending": False})

    def test_set_and_applied(self):
        self.assertEqual(nc.proxmox_cpu_state([{"key": "cpu", "value": "x86-64-v2-AES"}]),
                         {"current": "x86-64-v2-AES", "next": "x86-64-v2-AES", "pending": False})

    def test_waiting_for_restart(self):
        self.assertEqual(nc.proxmox_cpu_state([{"key": "cpu", "pending": "x86-64-v2-AES"}]),
                         {"current": "kvm64", "next": "x86-64-v2-AES", "pending": True})
        self.assertEqual(nc.proxmox_cpu_state([{"key": "cpu", "value": "x86-64-v2", "pending": "host"}]),
                         {"current": "x86-64-v2", "next": "host", "pending": True})

    def test_deleted(self):
        self.assertEqual(nc.proxmox_cpu_state([{"key": "cpu", "value": "host", "delete": 1}]),
                         {"current": "host", "next": "kvm64", "pending": True})

    def test_other_keys_pending(self):
        state = nc.proxmox_cpu_state([{"key": "cpu", "value": "host"},
                                      {"key": "memory", "value": 2048, "pending": 4096}])
        self.assertFalse(state["pending"])

    def test_flags_and_cputype_prefix(self):
        state = nc.proxmox_cpu_state([{"key": "cpu", "value": "cputype=host,flags=+aes"}])
        self.assertEqual(state["current"], "host")

    def test_empty_response(self):
        self.assertEqual(nc.proxmox_cpu_state(None)["current"], "kvm64")


if __name__ == "__main__":
    unittest.main()
