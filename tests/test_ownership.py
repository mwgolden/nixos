"""Tests for the ownership functions in plugins/filter/network_config.py:
tags, orphans, and what destroying a network deletes.

    .venv/bin/python -m unittest discover -s tests
"""

import importlib.util
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "networks"
spec = importlib.util.spec_from_file_location(
    "network_config", ROOT / "plugins" / "filter" / "network_config.py")
nc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nc)


def inventory():
    configs = {p.stem: yaml.safe_load(p.read_text()) for p in FIXTURES.glob("*.yaml")}
    return nc.network_config_inventory(configs)


def vm(vmid, name, tags="", description="", **config):
    return {"vmid": vmid, "name": name, "config": dict(tags=tags, description=description, **config)}


class Tags(unittest.TestCase):
    def test_tags_for_a_host(self):
        self.assertEqual(nc.nixlab_tags(inventory()["hosts"]["postgres"]),
                         ["nixlab", "net-lab", "type-postgres"])

    def test_merge_keeps_other_tags_and_replaces_ours(self):
        merged = nc.proxmox_tags_merge("backup;nixlab;net-home;type-postgres",
                                       ["nixlab", "net-lab", "type-postgres"])
        self.assertEqual(merged, "backup;nixlab;net-lab;type-postgres")

    def test_merge_untagged(self):
        self.assertEqual(nc.proxmox_tags_merge(None, ["nixlab", "net-lab", "type-router"]),
                         "nixlab;net-lab;type-router")


class Ownership(unittest.TestCase):
    def setUp(self):
        self.inv = inventory()

    def check(self, network, vms):
        return nc.network_config_ownership(self.inv, network, vms)

    def test_declared_and_tagged_is_fine(self):
        r = self.check("lab", [vm(112, "postgres", "nixlab;net-lab;type-postgres"),
                               vm(113, "router", "nixlab;net-lab;type-router")])
        self.assertEqual(r, {"orphans": [], "moved": [], "untagged": [], "conflicts": []})

    def test_removed_from_file_is_an_orphan(self):
        r = self.check("lab", [vm(120, "oldapp", "nixlab;net-lab;type-webserver",
                                  "nixlab-address: 10.1.0.20 on vmbr1")])
        self.assertEqual([(o["vmid"], o["type"], o["address"]["ip"]) for o in r["orphans"]],
                         [(120, "webserver", "10.1.0.20")])
        self.assertEqual(r["conflicts"], [])

    def test_orphan_holding_a_declared_address(self):
        r = self.check("lab", [vm(120, "oldpg", "nixlab;net-lab;type-postgres",
                                  "nixlab-address: 10.1.0.12 on vmbr1")])
        self.assertEqual([(c["name"], c["used_by"]) for c in r["conflicts"]], [("oldpg", "postgres")])

    def test_moved_to_another_file_is_not_an_orphan(self):
        # gitea is declared in home.yaml but still tagged for lab.
        r = self.check("lab", [vm(114, "gitea", "nixlab;net-lab;type-gitea")])
        self.assertEqual(r["orphans"], [])
        self.assertEqual([(m["name"], m["declared_in"]) for m in r["moved"]], [("gitea", "home")])

    def test_untagged_declared_host(self):
        r = self.check("lab", [vm(112, "postgres")])
        self.assertEqual([u["name"] for u in r["untagged"]], ["postgres"])
        self.assertEqual(r["orphans"], [])

    def test_untagged_unknown_vm_is_ignored(self):
        r = self.check("lab", [vm(300, "someone-elses", "backup")])
        self.assertEqual(r, {"orphans": [], "moved": [], "untagged": [], "conflicts": []})

    def test_other_networks_tags_are_ignored(self):
        r = self.check("lab", [vm(120, "oldapp", "nixlab;net-home;type-webserver")])
        self.assertEqual(r["orphans"], [])

    def test_same_name_other_id_is_an_orphan(self):
        r = self.check("lab", [vm(212, "postgres", "nixlab;net-lab;type-postgres")])
        self.assertEqual([o["vmid"] for o in r["orphans"]], [212])


class DestroyOrder(unittest.TestCase):
    def test_tagged_only_routers_last_skip_moved(self):
        vms = [vm(113, "router", "nixlab;net-lab;type-router"),
               vm(112, "postgres", "nixlab;net-lab;type-postgres"),
               vm(120, "oldapp", "nixlab;net-lab;type-webserver"),
               vm(114, "gitea", "nixlab;net-lab;type-gitea"),     # moved to home
               vm(130, "unmanaged"),
               vm(111, "webserver", "nixlab;net-home;type-webserver")]
        order = nc.network_config_destroy_order(inventory(), "lab", vms)
        self.assertEqual([v["name"] for v in order], ["postgres", "oldapp", "router"])


class BridgeUsers(unittest.TestCase):
    def test_finds_cards_on_the_bridge(self):
        vms = [vm(113, "router", net0="virtio=AA,bridge=vmbr0", net1="virtio=BB,bridge=vmbr1"),
               vm(112, "postgres", net0="virtio=CC,bridge=vmbr1,firewall=1"),
               vm(111, "webserver", net0="virtio=DD,bridge=vmbr10")]
        self.assertEqual(nc.proxmox_bridge_users(vms, "vmbr1"), ["router", "postgres"])


if __name__ == "__main__":
    unittest.main()
