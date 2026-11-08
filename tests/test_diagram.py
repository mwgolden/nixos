"""Tests for plugins/filter/network_diagram.py.

    .venv/bin/python -m unittest discover -s tests

The full output for the fixture networks is compared with the files in
tests/fixtures/diagrams/. After changing the diagrams on purpose, rewrite
them with:

    UPDATE_DIAGRAMS=1 .venv/bin/python -m unittest discover -s tests -p test_diagram.py
"""

import importlib.util
import os
import re
import unittest

from test_derived import KEY, add_vpn, host, inventory
from test_dmz import add_dmz
from test_network_config import ROOT

spec = importlib.util.spec_from_file_location("network_diagram", ROOT / "plugins" / "filter" / "network_diagram.py")
nd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nd)

GOLDEN = ROOT / "tests" / "fixtures" / "diagrams"


def full(configs):
    """lab with a DMZ, an external proxy route, a reach: rule and a VPN."""
    add_dmz(configs)
    add_vpn(configs)
    host(configs, "lab", "proxy")["reach"] = [{"host": "postgres", "port": 5432}]


def mermaid(text):
    return text.split("```mermaid\n", 1)[1].split("```", 1)[0]


class Golden(unittest.TestCase):
    def check(self, name, text):
        path = GOLDEN / name
        if os.environ.get("UPDATE_DIAGRAMS"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        self.assertEqual(text, path.read_text())

    def test_lab(self):
        inv = inventory(full)
        self.check("lab.md", nd.network_diagram(inv, "lab", nd.network_diagram_deployed(inv)))

    def test_home(self):
        inv = inventory()
        self.check("home.md", nd.network_diagram(inv, "home", nd.network_diagram_deployed(inv)))

    def test_index(self):
        inv = inventory(full)
        self.check("README.md", nd.network_diagram_index(inv, ["home", "lab"], nd.network_diagram_deployed(inv)))


class Content(unittest.TestCase):
    def setUp(self):
        self.inv = inventory(full)
        self.all = nd.network_diagram_deployed(self.inv)

    def test_same_output_every_time(self):
        self.assertEqual(nd.network_diagram(self.inv, "lab", self.all),
                         nd.network_diagram(inventory(full), "lab", list(reversed(self.all))))

    def test_edges(self):
        chart = mermaid(nd.network_diagram(self.inv, "lab", self.all))
        self.assertIn('up <-->|"ens18 WAN 192.168.1.13"| h_router', chart)
        self.assertIn('h_router <-->|"ens20 DMZ 10.1.1.1"| dmz', chart)
        self.assertIn('up -.->|"port forward tcp 192.168.1.13:5432"| h_postgres', chart)
        self.assertIn('h_proxy -.->|"route git (external), tcp 3000"| h_forge', chart)
        # The proxy's own 443 and 80 forwards are drawn as the external route.
        self.assertNotIn("port forward tcp 192.168.1.13:443", chart)
        self.assertNotIn("port forward tcp 192.168.1.13:80", chart)
        self.assertIn('up -.->|"external routes 192.168.1.13:443<br/>git.lab.home.arpa"| h_proxy', chart)
        # reach: is drawn; the DMZ rule a proxy route makes isn't drawn twice.
        self.assertIn('h_proxy -.->|"reach tcp 5432"| h_postgres', chart)
        self.assertNotIn("reach tcp 3000", chart)
        self.assertIn('vpn -.->|"udp 192.168.1.13:51820"| h_router', chart)

    def test_hosts_in_their_zones(self):
        chart = mermaid(nd.network_diagram(self.inv, "lab", self.all))
        lan = chart.split("subgraph lan", 1)[1].split("    end", 1)[0]
        dmz = chart.split("subgraph dmz", 1)[1].split("    end", 1)[0]
        self.assertIn("h_postgres[", lan)
        self.assertIn("h_forge[", lan)
        self.assertIn("h_proxy[", dmz)
        self.assertNotIn("h_router[", lan + dmz)

    def test_not_deployed(self):
        text = nd.network_diagram(self.inv, "lab", [h for h in self.all if h != "lab.forge"])
        self.assertIn("not deployed", text)
        self.assertIn("    class h_forge pending", text)
        self.assertIn("| forge | gitea | 140 | lan | 10.1.0.14 | tcp 3000 | 40 GB on local-lvm | no |", text)
        self.assertIn("3 of 4 hosts deployed", text)

    def test_router_not_deployed_on_home(self):
        text = nd.network_diagram(self.inv, "home", [h for h in self.all if h != "lab.router"])
        self.assertIn("    class r_lab pending", text)

    def test_no_keys(self):
        text = nd.network_diagram(self.inv, "lab", self.all) + nd.network_diagram_index(self.inv, ["home", "lab"], self.all)
        self.assertNotIn(KEY, text)
        self.assertIn("| phone | 10.201.0.3 |", text)

    def test_node_ids_and_labels(self):
        def mutate(configs):
            host(configs, "lab", "postgres")["name"] = "end-db"
        inv = inventory(mutate)
        chart = mermaid(nd.network_diagram(inv, "lab", nd.network_diagram_deployed(inv)))
        self.assertIn("h_end_db[", chart)
        self.assertEqual(nd._label('a "b" <c>', "d"), '"a #quot;b#quot; #lt;c#gt;<br/>d"')
        # Every node ID is letters, digits and '_'.
        for node in re.findall(r"^\s*(\w[\w-]*)[\[(]", chart, re.M):
            self.assertRegex(node, r"^[A-Za-z][A-Za-z0-9_]*$")

    def test_same_names_in_two_networks(self):
        def mutate(configs):
            lab2 = {"network": dict(configs["lab"]["network"], name="lab2", bridge="vmbr6",
                                    cidr="10.6.0.0/24", gateway="10.6.0.1", nameserver="10.6.0.1",
                                    dhcp={"start": "10.6.0.100", "end": "10.6.0.199"}),
                    "hosts": [{"name": "router", "type": "router", "vm_id": 613, "ip": "10.6.0.1",
                               "wan_ip": "192.168.1.63"}]}
            configs["lab2"] = lab2
        inv = inventory(mutate)
        deployed = nd.network_diagram_deployed(inv)
        lab2 = nd.network_diagram(inv, "lab2", deployed)
        self.assertIn("router, VM 613", lab2)
        self.assertNotIn("VM 113", lab2)
        home = nd.network_diagram(inv, "home", deployed)
        self.assertIn("router of lab, VM 113", home)
        self.assertIn("router of lab2, VM 613", home)


class Deployed(unittest.TestCase):
    def test_by_id_and_name(self):
        inv = inventory()
        vms = [{"vmid": 113, "name": "router"}, {"vmid": 112, "name": "someone-else"}]
        self.assertEqual(nd.network_diagram_deployed(inv, vms), ["lab.router"])

    def test_without_proxmox_everything_counts(self):
        inv = inventory()
        self.assertEqual(nd.network_diagram_deployed(inv, None), sorted(inv["hosts"]))

    def test_tagged_networks(self):
        vms = [{"vmid": 112, "name": "postgres", "tags": "nixlab;net-lab;type-postgres"}]
        self.assertEqual(nd.vm_tagged_networks(vms, 112), ["lab"])
        self.assertEqual(nd.vm_tagged_networks(vms, 999), [])

    def test_networks_with_deployed_hosts(self):
        inv = inventory()
        self.assertEqual(nd.networks_with_deployed_hosts(inv, ["home", "lab"], ["lab.router"]), ["lab"])
        self.assertEqual(nd.networks_with_deployed_hosts(inv, ["home", "lab"], []), [])

    def test_targets_add_upstream(self):
        inv = inventory()
        self.assertEqual(nd.network_diagram_targets(inv, ["lab"]), ["lab", "home"])
        self.assertEqual(nd.network_diagram_targets(inv, ["home", "lab", "gone"]), ["home", "lab"])


if __name__ == "__main__":
    unittest.main()
