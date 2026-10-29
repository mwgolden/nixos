"""Tests for the inventory and placement functions in
plugins/filter/network_config.py.

    .venv/bin/python -m unittest discover -s tests
"""

import importlib.util
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "network_config", ROOT / "plugins" / "filter" / "network_config.py")
nc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nc)

TEMPLATE_IP, TEMPLATE_BRIDGE = "192.168.1.10", "vmbr0"


def inventory():
    configs = {p.stem: yaml.safe_load(p.read_text()) for p in (ROOT / "networks").glob("*.yaml")}
    return nc.network_config_inventory(configs)


class Inventory(unittest.TestCase):
    def setUp(self):
        self.inv = inventory()

    def test_networks(self):
        lab = self.inv["networks"]["lab"]
        self.assertEqual((lab["router"], lab["router_wan_ip"], lab["prefix_length"]),
                         ("router", "192.168.1.13", 24))
        self.assertEqual(self.inv["networks"]["home"]["router"], "")

    def test_isolated_host_attaches_to_its_network(self):
        pg = self.inv["hosts"]["postgres"]
        self.assertEqual(pg["attach"], {
            "network": "lab", "bridge": "vmbr1", "ip": "10.1.0.12", "prefix_length": 24,
            "gateway": "10.1.0.1", "nameserver": "10.1.0.1", "via_router": "router"})
        self.assertEqual(pg["data_disk"], {"serial": "postgres-data", "size_gb": 20, "storage": "local-lvm"})
        self.assertEqual(pg["nics"], [])

    def test_router_attaches_upstream(self):
        r = self.inv["hosts"]["router"]
        self.assertEqual(r["attach"]["bridge"], "vmbr0")
        self.assertEqual(r["attach"]["ip"], "192.168.1.13")
        self.assertEqual(r["attach"]["gateway"], "192.168.1.1")
        self.assertEqual(r["attach"]["via_router"], "")
        self.assertEqual(r["ip"], "10.1.0.1")
        self.assertEqual(r["nics"], [{"interface": "net1", "bridge": "vmbr1"}])

    def test_home_host(self):
        w = self.inv["hosts"]["webserver"]
        self.assertEqual((w["attach"]["ip"], w["attach"]["via_router"], w["data_disk"]),
                         ("192.168.1.11", "", {}))


class RecordedAddress(unittest.TestCase):
    def test_round_trip_keeps_notes(self):
        notes = nc.record_address("My notes\nmore", "10.1.0.12", "vmbr1")
        self.assertEqual(notes, "My notes\nmore\nnixlab-address: 10.1.0.12 on vmbr1")
        self.assertEqual(nc.recorded_address(notes), {"ip": "10.1.0.12", "bridge": "vmbr1"})
        again = nc.record_address(notes, "192.168.1.12", "vmbr0")
        self.assertEqual(again, "My notes\nmore\nnixlab-address: 192.168.1.12 on vmbr0")

    def test_empty(self):
        self.assertEqual(nc.record_address(None, "1.2.3.4", "vmbr0"), "nixlab-address: 1.2.3.4 on vmbr0")
        self.assertEqual(nc.recorded_address(""), {})


class Placement(unittest.TestCase):
    def setUp(self):
        self.inv = inventory()

    def places(self, name, net0, description="", new_clone=False):
        vm = self.inv["hosts"][name]
        return [(c["ip"], c["bridge"], c["via_router"]) for c in nc.placement_candidates(
            vm, self.inv, net0, description, new_clone, TEMPLATE_IP, TEMPLATE_BRIDGE)]

    def test_new_clone(self):
        self.assertEqual(self.places("postgres", "", new_clone=True),
                         [("192.168.1.10", "vmbr0", "")])

    def test_settled_isolated_vm_without_record(self):
        # A VM deployed before addresses were recorded.
        self.assertEqual(self.places("postgres", "virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr1"),
                         [("10.1.0.12", "vmbr1", "router")])

    def test_settled_home_vm(self):
        self.assertEqual(self.places("gitea", "virtio=AA,bridge=vmbr0"),
                         [("192.168.1.14", "vmbr0", ""), ("192.168.1.10", "vmbr0", "")])

    def test_entry_moved_to_another_network(self):
        # postgres was at 192.168.1.12 on home; its entry is now in lab.
        self.assertEqual(
            self.places("postgres", "virtio=AA,bridge=vmbr0", "nixlab-address: 192.168.1.12 on vmbr0"),
            [("192.168.1.12", "vmbr0", ""), ("192.168.1.10", "vmbr0", ""), ("10.1.0.12", "vmbr1", "router")])

    def test_card_moved_but_address_did_not(self):
        self.assertEqual(
            self.places("postgres", "virtio=AA,bridge=vmbr1", "nixlab-address: 192.168.1.12 on vmbr0"),
            [("10.1.0.12", "vmbr1", "router"), ("192.168.1.12", "vmbr0", "")])

    def test_router_found_on_wan(self):
        self.assertEqual(self.places("router", "virtio=AA,bridge=vmbr0", "nixlab-address: 192.168.1.13 on vmbr0"),
                         [("192.168.1.13", "vmbr0", ""), ("192.168.1.10", "vmbr0", "")])


if __name__ == "__main__":
    unittest.main()
