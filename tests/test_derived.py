"""Tests for the configuration derived from the network files (Phase 6):
port forwards from expose:, DNS records and postgres client networks.

    .venv/bin/python -m unittest discover -s tests
"""

import unittest

from test_network_config import load_networks, network_config


def inventory(mutate=None):
    configs = {f["file"]: f["config"] for f in load_networks()}
    if mutate:
        mutate(configs)
    return network_config.network_config_inventory(configs)


def host(configs, network, name):
    return next(h for h in configs[network]["hosts"] if h["name"] == name)


class PortForwards(unittest.TestCase):
    def test_lab_forward_from_expose(self):
        lab = inventory()["networks"]["lab"]
        self.assertEqual(lab["port_forwards"], [
            {"name": "postgres", "host": "postgres", "proto": "tcp",
             "wan_port": 5432, "lan_ip": "10.1.0.12", "lan_port": 5432}])

    def test_named_entries_and_wan_port(self):
        def mutate(configs):
            host(configs, "lab", "postgres")["expose"] = [
                {"name": "pg", "port": 5432, "wan_port": 15432},
                {"name": "dns", "proto": "udp", "port": 53, "wan_port": 5353}]
        inv = inventory(mutate)
        self.assertEqual(
            [(f["name"], f["proto"], f["wan_port"], f["lan_port"]) for f in inv["networks"]["lab"]["port_forwards"]],
            [("postgres-pg", "tcp", 15432, 5432), ("postgres-dns", "udp", 5353, 53)])
        self.assertEqual(inv["hosts"]["postgres"]["expose"][0],
                         {"name": "postgres-pg", "proto": "tcp", "port": 5432, "wan_port": 15432})

    def test_home_has_no_forwards(self):
        self.assertEqual(inventory()["networks"]["home"]["port_forwards"], [])


class Dns(unittest.TestCase):
    def test_default_domain_and_records(self):
        lab = inventory()["networks"]["lab"]
        self.assertEqual(lab["domain"], "lab.home.arpa")
        self.assertEqual(lab["dns_records"], [
            {"name": "router", "fqdn": "router.lab.home.arpa", "ip": "10.1.0.1"},
            {"name": "postgres", "fqdn": "postgres.lab.home.arpa", "ip": "10.1.0.12"}])

    def test_domain_setting(self):
        def mutate(configs):
            configs["lab"]["network"]["domain"] = "lab.example.internal"
        lab = inventory(mutate)["networks"]["lab"]
        self.assertEqual(lab["dns_records"][1]["fqdn"], "postgres.lab.example.internal")


class ClientNetworks(unittest.TestCase):
    def test_exposed_isolated_host_includes_upstream(self):
        inv = inventory()
        self.assertEqual(network_config.host_client_networks(inv["hosts"]["postgres"], inv),
                         ["10.1.0.0/24", "192.168.1.0/24"])

    def test_unexposed_isolated_host_is_own_network_only(self):
        def mutate(configs):
            del host(configs, "lab", "postgres")["expose"]
        inv = inventory(mutate)
        self.assertEqual(network_config.host_client_networks(inv["hosts"]["postgres"], inv),
                         ["10.1.0.0/24"])

    def test_home_host(self):
        inv = inventory()
        self.assertEqual(network_config.host_client_networks(inv["hosts"]["gitea"], inv),
                         ["192.168.1.0/24"])

    def test_names_resolve_to_subnets(self):
        inv = inventory()
        self.assertEqual(network_config.network_cidrs(["lab", "10.9.0.0/16", "home", "10.1.0.0/24"], inv),
                         ["10.1.0.0/24", "10.9.0.0/16", "192.168.1.0/24"])


if __name__ == "__main__":
    unittest.main()
