"""Tests for plugins/filter/network_config.py.

    .venv/bin/python -m unittest discover -s tests
"""

import copy
import importlib.util
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "network_config", ROOT / "plugins" / "filter" / "network_config.py")
network_config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(network_config)

TEMPLATE_VM_ID = 110
TEMPLATE_IP = "192.168.1.10"


def load_repo_networks():
    return [{"file": p.stem, "config": yaml.safe_load(p.read_text())}
            for p in sorted((ROOT / "networks").glob("*.yaml"))]


def errors(files):
    return network_config.network_config_errors(files, TEMPLATE_VM_ID, TEMPLATE_IP)


class RepoNetworks(unittest.TestCase):
    def test_repo_networks_are_valid(self):
        self.assertEqual(errors(load_repo_networks()), [])


class Examples(unittest.TestCase):
    def test_examples_are_valid_next_to_the_repo_networks(self):
        for path in sorted((ROOT / "networks" / "examples").glob("*.yaml")):
            with self.subTest(example=path.name):
                files = load_repo_networks() + [{"file": path.stem, "config": yaml.safe_load(path.read_text())}]
                self.assertEqual(errors(files), [])


class Mutations(unittest.TestCase):
    def setUp(self):
        self.files = load_repo_networks()
        self.by_name = {f["file"]: f["config"] for f in self.files}

    def host(self, network, name):
        return next(h for h in self.by_name[network]["hosts"] if h["name"] == name)

    def assertError(self, fragment):
        found = errors(self.files)
        self.assertTrue(any(fragment in e for e in found),
                        f"no error containing {fragment!r} in {found}")

    def test_duplicate_vm_id_across_networks(self):
        self.host("lab", "postgres")["vm_id"] = 111
        self.assertError("vm_id 111 is already used by host webserver")

    def test_template_vm_id(self):
        self.host("home", "webserver")["vm_id"] = 110
        self.assertError("is the template's ID")

    def test_duplicate_name_across_networks(self):
        self.host("lab", "postgres")["name"] = "gitea"
        self.assertError("host name gitea is already used")

    def test_duplicate_address_router_wan(self):
        self.host("home", "webserver")["ip"] = "192.168.1.13"
        self.assertError("address 192.168.1.13 is already used")

    def test_ip_outside_cidr(self):
        self.host("lab", "postgres")["ip"] = "10.2.0.12"
        self.assertError("is not a usable address in lab's 10.1.0.0/24")

    def test_ip_in_dhcp_range(self):
        self.host("lab", "postgres")["ip"] = "10.1.0.150"
        self.assertError("inside lab's DHCP range")

    def test_template_ip(self):
        self.host("home", "gitea")["ip"] = "192.168.1.10"
        self.assertError("is the template's address")

    def test_gateway_ip(self):
        self.host("home", "gitea")["ip"] = "192.168.1.1"
        self.assertError("is home's gateway")

    def test_broadcast_ip(self):
        self.host("home", "gitea")["ip"] = "192.168.1.255"
        self.assertError("is not a usable address")

    def test_reserved_ip(self):
        self.by_name["home"]["network"]["reserved"] = ["192.168.1.14"]
        self.assertError("is reserved in network home")

    def test_router_ip_must_be_gateway(self):
        self.host("lab", "router")["ip"] = "10.1.0.2"
        self.assertError("a router's ip must be its network's gateway")

    def test_router_wan_ip_on_upstream(self):
        self.host("lab", "router")["wan_ip"] = "10.1.0.13"
        self.assertError("wan_ip 10.1.0.13 is not a usable address in home's")

    def test_isolated_needs_one_router(self):
        self.by_name["lab"]["hosts"] = [h for h in self.by_name["lab"]["hosts"] if h["type"] != "router"]
        self.assertError("needs exactly one host of type router")

    def test_home_cannot_have_router(self):
        router = copy.deepcopy(self.host("lab", "router"))
        router.update(name="router2", vm_id=199, ip="192.168.1.1")
        self.by_name["home"]["hosts"].append(router)
        self.assertError("a home network can't have a router host")

    def test_upstream_must_exist(self):
        self.by_name["lab"]["network"]["upstream"] = "nowhere"
        self.assertError("upstream 'nowhere' is not a network")

    def test_shared_bridge(self):
        self.by_name["lab"]["network"]["bridge"] = "vmbr0"
        self.assertError("bridge vmbr0 is already used")

    def test_overlapping_cidr(self):
        self.by_name["lab"]["network"]["cidr"] = "192.168.0.0/16"
        self.assertError("overlaps 192.168.1.0/24")

    def test_name_must_match_file(self):
        self.by_name["lab"]["network"]["name"] = "other"
        self.assertError("network.name must be 'lab'")

    def test_unknown_host_key(self):
        self.host("lab", "postgres")["cores"] = 4
        self.assertError("unknown setting cores")

    def test_unknown_type(self):
        self.host("home", "webserver")["type"] = "minio"
        self.assertError("type must be one of")

    def test_data_disk_required(self):
        del self.host("home", "gitea")["data_disk"]
        self.assertError("a gitea host needs a data_disk")

    def test_port_forward_target_must_be_a_host(self):
        self.host("lab", "router")["settings"]["port_forwards"][0]["lan_ip"] = "10.1.0.99"
        self.assertError("lan_ip 10.1.0.99 is not a host on network lab")

    def test_port_forward_ssh(self):
        self.host("lab", "router")["settings"]["port_forwards"][0]["wan_port"] = 22
        self.assertError("TCP 22 can't be forwarded")

    def test_duplicate_port_forward(self):
        fwds = self.host("lab", "router")["settings"]["port_forwards"]
        fwds.append(dict(fwds[0], name="again"))
        self.assertError("tcp/5432 is already forwarded")

    def test_isolated_needs_dhcp(self):
        del self.by_name["lab"]["network"]["dhcp"]
        self.assertError("an isolated network needs a dhcp block")

    def test_dhcp_outside_cidr(self):
        self.by_name["lab"]["network"]["dhcp"]["end"] = "10.1.1.10"
        self.assertError("must be inside 10.1.0.0/24")


VMS = [{"vmid": 110, "name": "nixos-template"}, {"vmid": 111, "name": "webserver"},
       {"vmid": 112, "name": "postgres"}, {"vmid": 113, "name": "router"},
       {"vmid": 200, "name": "unrelated"}]
IFACES = [{"iface": "vmbr0", "type": "bridge", "bridge_ports": "eno1", "cidr": "192.168.1.5/24"},
          {"iface": "vmbr1", "type": "bridge", "bridge_ports": None, "cidr": None}]


class Proxmox(unittest.TestCase):
    def setUp(self):
        self.configs = {f["file"]: f["config"] for f in load_repo_networks()}

    def check(self, vms=VMS, ifaces=IFACES):
        return network_config.network_config_proxmox_errors(self.configs, vms, ifaces, 110, "com")

    def test_matching_state_is_valid(self):
        self.assertEqual(self.check(), [])

    def test_missing_template(self):
        self.assertIn("The template, VM 110, does not exist", self.check(vms=VMS[1:])[0])

    def test_id_with_other_name(self):
        vms = VMS + [{"vmid": 114, "name": "something-else"}]
        self.assertIn("VM 114 exists but is named 'something-else'", self.check(vms=vms)[0])

    def test_name_under_other_id(self):
        vms = VMS + [{"vmid": 214, "name": "gitea"}]
        self.assertIn("already exists as VM 214", self.check(vms=vms)[0])

    def test_missing_home_bridge(self):
        self.assertIn("bridge vmbr0 does not exist", self.check(ifaces=IFACES[1:])[0])

    def test_isolated_bridge_may_be_absent(self):
        self.assertEqual(self.check(ifaces=IFACES[:1]), [])

    def test_isolated_bridge_with_port(self):
        ifaces = [IFACES[0], dict(IFACES[1], bridge_ports="eno2")]
        self.assertIn("is not an isolated bridge", self.check(ifaces=ifaces)[0])

    def test_summary(self):
        self.assertEqual(network_config.network_config_summary(self.configs, VMS),
                         ["home: 1 of 3 hosts exist, to create: gitea, garage",
                          "lab: 2 of 2 hosts exist"])


if __name__ == "__main__":
    unittest.main()
