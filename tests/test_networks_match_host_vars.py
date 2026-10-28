"""Checks that networks/*.yaml describes the same VMs as hosts/*/vars.yaml.

The host playbooks still read hosts/*/vars.yaml until they move onto the
network files. Until then the two must agree, or the move would change a
VM's ID, address or disk.

    .venv/bin/python -m unittest discover -s tests
"""

import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load(path):
    return yaml.safe_load((ROOT / path).read_text())


class NetworksMatchHostVars(unittest.TestCase):
    def setUp(self):
        self.hosts = {}
        for path in sorted((ROOT / "networks").glob("*.yaml")):
            config = yaml.safe_load(path.read_text())
            for host in config.get("hosts") or []:
                self.hosts[host["name"]] = (config["network"], host)
        self.proxmox = load("proxmox/vars.yaml")

    def test_every_host_folder_is_declared(self):
        folders = {p.parent.name for p in (ROOT / "hosts").glob("*/vars.yaml")}
        self.assertEqual(folders, set(self.hosts))

    def test_vm_settings_match(self):
        for name, (net, host) in self.hosts.items():
            with self.subTest(host=name):
                old = load(f"hosts/{name}/vars.yaml")
                self.assertEqual(host["vm_id"], old[f"{name}_vm_id"])
                self.assertEqual(name, old[f"{name}_vm_name"])
                self.assertEqual(host.get("full_clone", False), old[f"{name}_full_clone"])
                if host["type"] == "router":
                    self.assertEqual(host["wan_ip"], old["router_ip"])
                    self.assertEqual(host["ip"], old["router_lan_ip"])
                    continue
                self.assertEqual(net["type"], old[f"{name}_network"])
                key = "isolated_ip" if net["type"] == "isolated" else "ip"
                self.assertEqual(host["ip"], old[f"{name}_{key}"])
                if "data_disk" in host:
                    self.assertEqual(host["data_disk"]["size_gb"], old[f"{name}_data_disk_gb"])
                    self.assertEqual(host["data_disk"]["storage"], old[f"{name}_data_disk_storage"])

    def test_router_settings_match(self):
        net, host = self.hosts["router"]
        old = load("hosts/router/vars.yaml")
        settings = host["settings"]
        self.assertEqual(net["bridge"], self.proxmox["isolated_bridge"])
        self.assertEqual(net["cidr"].split("/")[1], str(old["router_lan_prefix_length"]))
        self.assertEqual(net["dhcp"]["start"], old["router_dhcp_range_start"])
        self.assertEqual(net["dhcp"]["end"], old["router_dhcp_range_end"])
        self.assertEqual(net["dhcp"]["lease_time"], old["router_dhcp_lease_time"])
        self.assertEqual(settings["dns_servers"], old["router_dns_servers"])
        self.assertEqual(settings["blocked_networks"], old["router_blocked_networks"])
        self.assertEqual(settings["port_forwards"], old["router_port_forwards"])

    def test_home_network_matches(self):
        home = load("networks/home.yaml")["network"]
        self.assertEqual(home["bridge"], self.proxmox["network_bridge"])
        self.assertEqual(home["gateway"], self.proxmox["network_gateway"])
        self.assertEqual(home["nameserver"], self.proxmox["network_nameserver"])
        self.assertEqual(home["cidr"].split("/")[1], str(self.proxmox["network_prefix_length"]))


if __name__ == "__main__":
    unittest.main()
