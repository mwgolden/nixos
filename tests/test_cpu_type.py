"""Tests for VM hardware settings (docs/plans/completed/CPU-TYPE.md): cpu:, cores:
and memory_mb: on hosts, vm_cpu_type, the inventory, the node capacity
checks, and reading Proxmox's pending changes.

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


def cpu(pending):
    """The cpu part of proxmox_hardware_state."""
    return nc.proxmox_hardware_state(pending)["options"]["cpu"]


class PendingState(unittest.TestCase):
    """GET /nodes/<node>/qemu/<vmid>/pending returns every option with its
    value, plus pending (a change waiting for a restart) or delete."""

    def test_no_cpu_option(self):
        self.assertEqual(cpu([{"key": "memory", "value": 4096}]),
                         {"current": "kvm64", "next": "kvm64", "pending": False})

    def test_set_and_applied(self):
        self.assertEqual(cpu([{"key": "cpu", "value": "x86-64-v2-AES"}]),
                         {"current": "x86-64-v2-AES", "next": "x86-64-v2-AES", "pending": False})

    def test_waiting_for_restart(self):
        self.assertEqual(cpu([{"key": "cpu", "pending": "x86-64-v2-AES"}]),
                         {"current": "kvm64", "next": "x86-64-v2-AES", "pending": True})
        self.assertEqual(cpu([{"key": "cpu", "value": "x86-64-v2", "pending": "host"}]),
                         {"current": "x86-64-v2", "next": "host", "pending": True})

    def test_deleted(self):
        self.assertEqual(cpu([{"key": "cpu", "value": "host", "delete": 1}]),
                         {"current": "host", "next": "kvm64", "pending": True})

    def test_flags_and_cputype_prefix(self):
        self.assertEqual(cpu([{"key": "cpu", "value": "cputype=host,flags=+aes"}])["current"], "host")

    def test_empty_response(self):
        state = nc.proxmox_hardware_state(None)
        self.assertEqual(state["options"]["cpu"]["current"], "kvm64")
        self.assertEqual(state["options"]["cores"]["current"], "1")
        self.assertEqual(state["options"]["memory"]["current"], "512")
        self.assertFalse(state["pending"])

    def test_cores_and_memory(self):
        state = nc.proxmox_hardware_state([
            {"key": "cpu", "value": "x86-64-v2-AES"},
            {"key": "cores", "value": 2, "pending": 4},
            {"key": "memory", "value": "4096", "pending": "8192"}])
        self.assertTrue(state["pending"])
        self.assertEqual(state["changes"], ["cores 2 -> 4", "memory 4096 -> 8192 MB"])
        self.assertFalse(state["options"]["cpu"]["pending"])

    def test_other_keys_ignored(self):
        state = nc.proxmox_hardware_state([{"key": "cpu", "value": "host"}, {"key": "cores", "value": 2},
                                           {"key": "memory", "value": 4096},
                                           {"key": "net0", "value": "a", "pending": "b"}])
        self.assertFalse(state["pending"])


class Changes(unittest.TestCase):
    def test_wanted(self):
        self.assertEqual(nc.proxmox_hardware_wanted("host", 4, 8192),
                         {"cpu": "host", "cores": "4", "memory": "8192"})
        self.assertEqual(nc.proxmox_hardware_wanted("x86-64-v2-AES", 0, 0), {"cpu": "x86-64-v2-AES"})
        self.assertEqual(nc.proxmox_hardware_wanted("", 0, 0), {})

    def test_only_differences_sent(self):
        state = nc.proxmox_hardware_state([{"key": "cpu", "value": "x86-64-v2-AES"},
                                           {"key": "cores", "value": 2}, {"key": "memory", "value": 4096}])
        self.assertEqual(nc.proxmox_hardware_changes(state, nc.proxmox_hardware_wanted("x86-64-v2-AES", 4, 4096)),
                         {"cores": "4"})

    def test_waiting_change_not_sent_again(self):
        state = nc.proxmox_hardware_state([{"key": "cores", "value": 2, "pending": 4}])
        self.assertEqual(nc.proxmox_hardware_changes(state, {"cores": "4"}), {})

    def test_template_values_left_alone(self):
        state = nc.proxmox_hardware_state([{"key": "cores", "value": 2}, {"key": "memory", "value": 4096}])
        self.assertEqual(nc.proxmox_hardware_changes(state, nc.proxmox_hardware_wanted("", 0, 0)), {})


def with_setting(key, value, host_index=0):
    files = copy.deepcopy(load_networks())
    files[0]["config"]["hosts"][host_index][key] = value
    return files


class CoresAndMemory(unittest.TestCase):
    def test_allowed(self):
        for key, value in (("cores", 1), ("cores", 64), ("memory_mb", 512), ("memory_mb", 262144)):
            self.assertEqual(errors(with_setting(key, value)), [], (key, value))

    def test_rejected(self):
        for key, value in (("cores", 0), ("cores", 65), ("cores", "4"), ("cores", True), ("cores", 2.5),
                           ("memory_mb", 256), ("memory_mb", 300000), ("memory_mb", "8192")):
            found = errors(with_setting(key, value))
            self.assertTrue(any(f"{key} must be a whole number" in e for e in found), (key, value, found))

    def test_inventory(self):
        files = with_setting("cores", 4)
        files[0]["config"]["hosts"][0]["memory_mb"] = 8192
        inv = nc.network_config_inventory({f["file"]: f["config"] for f in files})
        first = files[0]["config"]["hosts"][0]["name"]
        host = inv["hosts"][f"{files[0]['file']}.{first}"]
        self.assertEqual((host["cores"], host["memory_mb"]), (4, 8192))
        others = [h for k, h in inv["hosts"].items() if k != host["id"]]
        self.assertTrue(all(h["cores"] == 0 and h["memory_mb"] == 0 for h in others))


class Capacity(unittest.TestCase):
    def configs(self, **settings):
        files = copy.deepcopy(load_networks())
        files[0]["config"]["hosts"][0].update(settings)
        return {f["file"]: f["config"] for f in files}

    def test_too_many_cores(self):
        self.assertEqual(nc.network_config_capacity_errors(self.configs(cores=8), 8), [])
        found = nc.network_config_capacity_errors(self.configs(cores=12), 8)
        self.assertEqual(len(found), 1)
        self.assertIn("12 is more than the 8 CPUs", found[0])

    def test_unknown_node_size_skips(self):
        self.assertEqual(nc.network_config_capacity_errors(self.configs(cores=64), 0), [])
        self.assertEqual(nc.network_config_capacity_warnings(self.configs(), [], 0, 4096), [])

    def test_memory_warning(self):
        configs = self.configs(memory_mb=200000)
        gib = 1024 ** 3
        self.assertEqual(len(nc.network_config_capacity_warnings(configs, [], 64 * gib, 4096)), 1)
        self.assertEqual(nc.network_config_capacity_warnings(configs, [], 1024 * gib, 4096), [])

    def test_memory_counts_existing_vms(self):
        configs = self.configs()
        vm_id = next(iter(configs.values()))["hosts"][0]["vm_id"]
        hosts = sum(len(c.get("hosts") or []) for c in configs.values())
        node = (hosts * 1024 + 1) * 1024 * 1024
        self.assertEqual(nc.network_config_capacity_warnings(configs, [], node, 1024), [])
        big = [{"vmid": vm_id, "config": {"memory": 100000}}]
        self.assertEqual(len(nc.network_config_capacity_warnings(configs, big, node, 1024)), 1)


if __name__ == "__main__":
    unittest.main()
