"""Tests for the deployment-check filters (roles/network_verify).

    .venv/bin/python -m unittest discover -s tests
"""

import unittest

from test_derived import add_proxy, host, inventory
from test_network_config import network_config as nc

SS = """LISTEN 0      4096         0.0.0.0:22        0.0.0.0:*
LISTEN 0      4096       127.0.0.1:2019      0.0.0.0:*
LISTEN 0      32       10.1.0.1%ens19:53       0.0.0.0:*
LISTEN 0      4096            [::]:5432          [::]:*
LISTEN 0      4096           [::1]:631          [::]:*
LISTEN 0      50  [::ffff:127.0.0.1]:45067          *:*
LISTEN 0      4096               *:9100             *:*
LISTEN 0      4096            [::]:22            [::]:*
"""


class Listeners(unittest.TestCase):
    def test_unexpected(self):
        self.assertEqual(nc.unexpected_listeners(SS, [22, 53]), ["[::]:5432", "*:9100"])

    def test_all_expected(self):
        self.assertEqual(nc.unexpected_listeners(SS, [22, 53, 5432, 9100]), [])

    def test_empty(self):
        self.assertEqual(nc.unexpected_listeners("", [22]), [])


class Blocked(unittest.TestCase):
    def test_isolated_host(self):
        inv = inventory()
        self.assertEqual(nc.blocked_targets(inv["hosts"]["postgres"], inv, "192.168.1.5"), [
            {"name": "home's gateway", "host": "192.168.1.1", "port": 53},
            {"name": "the Proxmox web interface", "host": "192.168.1.5", "port": 8006}])

    def test_other_isolated_networks(self):
        def mutate(configs):
            configs["lab2"] = {
                "network": dict(configs["lab"]["network"], name="lab2", bridge="vmbr5", cidr="10.5.0.0/24",
                                gateway="10.5.0.1", nameserver="10.5.0.1",
                                dhcp={"start": "10.5.0.100", "end": "10.5.0.199"}),
                "hosts": [{"name": "router2", "type": "router", "vm_id": 300, "ip": "10.5.0.1",
                           "wan_ip": "192.168.1.30"}]}
        inv = inventory(mutate)
        names = [t["name"] for t in nc.blocked_targets(inv["hosts"]["postgres"], inv)]
        self.assertEqual(names, ["home's gateway", "lab2's gateway"])

    def test_router_and_home_hosts(self):
        inv = inventory()
        self.assertEqual(nc.blocked_targets(inv["hosts"]["router"], inv, "x"), [])
        self.assertEqual(nc.blocked_targets(inv["hosts"]["gitea"], inv, "x"), [])


class ProxmoxState(unittest.TestCase):
    VMS = [{"vmid": 113, "status": "running",
            "config": {"net0": "virtio=A,bridge=vmbr0", "net1": "virtio=B,bridge=vmbr1"}},
           {"vmid": 112, "status": "stopped", "config": {"net0": "virtio=C,bridge=vmbr0"}}]

    def test_problems(self):
        inv = inventory()
        self.assertEqual(nc.network_verify_proxmox(inv, ["router", "postgres", "gitea"], self.VMS), {
            "postgres": ["VM 112 is stopped, not running.", "net0 is on vmbr0, not vmbr1."],
            "gitea": ["VM 114 doesn't exist in Proxmox."]})

    def test_router_lan_card(self):
        inv = inventory()
        vms = [{"vmid": 113, "status": "running", "config": {"net0": "virtio=A,bridge=vmbr0"}}]
        self.assertEqual(nc.network_verify_proxmox(inv, ["router"], vms),
                         {"router": ["net1 is on no bridge, not vmbr1."]})


class Unforwarded(unittest.TestCase):
    def test_lab(self):
        inv = inventory()
        listening = {"router": [22, 53], "postgres": [22, 5432, 9100], "gitea": [3000]}
        # 5432 is forwarded, 22 is the router's own, and gitea is on home.
        self.assertEqual(nc.unforwarded_ports(inv, "lab", listening), [53, 9100])

    def test_external_route_forwards_443_and_80(self):
        def mutate(configs):
            add_proxy(configs)
            host(configs, "lab", "postgres")["proxy"][0]["external"] = True
        inv = inventory(mutate)
        self.assertEqual(nc.unforwarded_ports(inv, "lab", {"proxy": [22, 80, 443, 2019]}), [2019])

    def test_home(self):
        self.assertEqual(nc.unforwarded_ports(inventory(), "home", {"gitea": [3000]}), [])


class SshArgs(unittest.TestCase):
    def test_direct(self):
        self.assertEqual(nc.nixlab_ssh_args("", "/k"), "-o StrictHostKeyChecking=accept-new")

    def test_through_router(self):
        self.assertEqual(
            nc.nixlab_ssh_args("192.168.1.13", "/k"),
            "-o StrictHostKeyChecking=accept-new -o ProxyCommand=\"ssh -i '/k' "
            "-o StrictHostKeyChecking=accept-new -o BatchMode=yes -W %h:%p admin@192.168.1.13\"")


if __name__ == "__main__":
    unittest.main()
