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



def add_proxy(configs):
    configs["lab"]["hosts"].append({"name": "proxy", "type": "proxy", "vm_id": 116, "ip": "10.1.0.10"})
    host(configs, "lab", "postgres")["proxy"] = [{"name": "pgweb", "port": 8080}]


class ProxyRoutes(unittest.TestCase):
    def test_routes_and_dns(self):
        lab = inventory(add_proxy)["networks"]["lab"]
        self.assertEqual(lab["proxy"], "proxy")
        self.assertEqual(lab["proxy_routes"], [
            {"name": "pgweb", "fqdn": "pgweb.lab.home.arpa", "host": "postgres",
             "backend_ip": "10.1.0.12", "port": 8080, "external": False}])
        # The route's name points at the proxy, not the backend.
        self.assertIn({"name": "pgweb", "fqdn": "pgweb.lab.home.arpa", "ip": "10.1.0.10"}, lab["dns_records"])

    def test_internal_routes_add_no_forwards(self):
        lab = inventory(add_proxy)["networks"]["lab"]
        self.assertEqual([f["name"] for f in lab["port_forwards"]], ["postgres"])
        self.assertEqual(lab["proxy_internal_sources"], ["10.1.0.0/24", "127.0.0.0/8"])

    def test_external_route_forwards_443_and_80(self):
        def mutate(configs):
            add_proxy(configs)
            add_vpn(configs)
            host(configs, "lab", "postgres")["proxy"][0]["external"] = True
        lab = inventory(mutate)["networks"]["lab"]
        self.assertTrue(lab["proxy_routes"][0]["external"])
        self.assertEqual(lab["port_forwards"][1:], [
            {"name": "proxy-https", "host": "proxy", "proto": "tcp", "wan_port": 443, "lan_ip": "10.1.0.10", "lan_port": 443},
            {"name": "proxy-http", "host": "proxy", "proto": "tcp", "wan_port": 80, "lan_ip": "10.1.0.10", "lan_port": 80}])
        self.assertEqual(lab["proxy_internal_sources"], ["10.1.0.0/24", "10.201.0.0/24", "127.0.0.0/8"])

    def test_no_proxy(self):
        self.assertEqual(inventory()["networks"]["lab"]["proxy"], "")


class ProxyValidation(unittest.TestCase):
    def setUp(self):
        self.files = load_networks()
        self.configs = {f["file"]: f["config"] for f in self.files}

    def errors(self):
        return network_config.network_config_errors(self.files, 110, "192.168.1.10")

    def assertError(self, fragment):
        found = self.errors()
        self.assertTrue(any(fragment in e for e in found), f"no error containing {fragment!r} in {found}")

    def test_valid(self):
        add_proxy(self.configs)
        self.assertEqual(self.errors(), [])

    def test_routes_need_a_proxy(self):
        host(self.configs, "lab", "postgres")["proxy"] = [{"name": "pgweb", "port": 8080}]
        self.assertError("the network has no host of type proxy")

    def test_one_proxy_only(self):
        add_proxy(self.configs)
        self.configs["lab"]["hosts"].append({"name": "proxy2", "type": "proxy", "vm_id": 117, "ip": "10.1.0.11"})
        self.assertError("only one proxy host")

    def test_route_name_clashes_with_host(self):
        add_proxy(self.configs)
        host(self.configs, "lab", "postgres")["proxy"] = [{"name": "router", "port": 8080}]
        self.assertError("same name as host router")

    def test_duplicate_route(self):
        add_proxy(self.configs)
        host(self.configs, "lab", "postgres")["proxy"].append({"name": "pgweb", "port": 9090})
        self.assertError("already a route to postgres")

    def test_bad_route(self):
        add_proxy(self.configs)
        host(self.configs, "lab", "postgres")["proxy"] = [{"name": "git.lab", "port": 0, "tls": True}]
        self.assertError("name must be one DNS label")
        self.assertError("port must be from 1 to 65535")
        self.assertError("unknown setting tls")

    def test_ldap_behind_proxy(self):
        add_proxy(self.configs)
        self.configs["lab"]["hosts"].append({"name": "ldap", "type": "ldap", "vm_id": 117, "ip": "10.1.0.17",
                                             "proxy": [{"name": "users", "port": 17170}]})
        self.assertEqual(self.errors(), [])

    def test_external_must_be_bool(self):
        add_proxy(self.configs)
        host(self.configs, "lab", "postgres")["proxy"][0]["external"] = "yes"
        self.assertError("external must be true or false")

    def test_external_on_home_network(self):
        self.configs["home"]["hosts"].append({"name": "hproxy", "type": "proxy", "vm_id": 120, "ip": "192.168.1.30"})
        host(self.configs, "home", "gitea")["proxy"] = [{"name": "git", "port": 3000, "external": True}]
        self.assertError("external is only used on isolated networks")

    def test_external_clashes_with_expose_443(self):
        add_proxy(self.configs)
        host(self.configs, "lab", "postgres")["proxy"][0]["external"] = True
        host(self.configs, "lab", "postgres")["expose"].append({"name": "web", "port": 8443, "wan_port": 443})
        self.assertError("need the router's tcp/443, which is already forwarded to postgres")

    def test_proxy_cannot_have_routes(self):
        add_proxy(self.configs)
        host(self.configs, "lab", "proxy")["proxy"] = [{"name": "self", "port": 80}]
        self.assertError("a proxy host can't have proxy: routes")



KEY = "xTIBA5rboUvnH4htodjb6e697QjLERt1NAB4mZqp8Dg="


def add_vpn(configs, **extra):
    host(configs, "lab", "router")["settings"]["vpn"] = dict({
        "cidr": "10.201.0.0/24",
        "peers": [{"name": "laptop", "ip": "10.201.0.2"},
                  {"name": "phone", "ip": "10.201.0.3", "public_key": KEY}]}, **extra)


class Vpn(unittest.TestCase):
    def test_inventory(self):
        inv = inventory(add_vpn)
        self.assertEqual(inv["networks"]["lab"]["vpn"], {
            "cidr": "10.201.0.0/24", "prefix_length": 24, "address": "10.201.0.1", "port": 51820,
            "endpoint": "192.168.1.13:51820",
            "peers": [{"name": "laptop", "ip": "10.201.0.2", "public_key": ""},
                      {"name": "phone", "ip": "10.201.0.3", "public_key": KEY}],
            "allowed_ips": ["10.1.0.0/24", "10.201.0.0/24"]})
        self.assertEqual(inv["networks"]["home"]["vpn"], {})

    def test_endpoint_and_port(self):
        inv = inventory(lambda c: add_vpn(c, endpoint="vpn.example.com", port=51900))
        self.assertEqual(inv["networks"]["lab"]["vpn"]["endpoint"], "vpn.example.com:51900")

    def test_postgres_allows_vpn_clients(self):
        inv = inventory(add_vpn)
        self.assertEqual(network_config.host_client_networks(inv["hosts"]["postgres"], inv),
                         ["10.1.0.0/24", "10.201.0.0/24", "192.168.1.0/24"])


class VpnValidation(unittest.TestCase):
    def setUp(self):
        self.files = load_networks()
        self.configs = {f["file"]: f["config"] for f in self.files}

    def assertError(self, fragment):
        found = network_config.network_config_errors(self.files, 110, "192.168.1.10")
        self.assertTrue(any(fragment in e for e in found), f"no error containing {fragment!r} in {found}")

    def vpn(self):
        return host(self.configs, "lab", "router")["settings"]["vpn"]

    def test_valid(self):
        add_vpn(self.configs)
        self.assertEqual(network_config.network_config_errors(self.files, 110, "192.168.1.10"), [])

    def test_cidr_overlaps_a_network(self):
        add_vpn(self.configs, cidr="10.1.0.0/16")
        self.assertError("settings.vpn.cidr 10.1.0.0/16 overlaps 10.1.0.0/24")

    def test_peer_ip_outside_cidr(self):
        add_vpn(self.configs)
        self.vpn()["peers"][0]["ip"] = "10.1.0.50"
        self.assertError("ip must be a usable address in settings.vpn.cidr")

    def test_peer_is_router_address(self):
        add_vpn(self.configs)
        self.vpn()["peers"][0]["ip"] = "10.201.0.1"
        self.assertError("is the router's own VPN address")

    def test_duplicate_peer(self):
        add_vpn(self.configs)
        self.vpn()["peers"][1].update(name="laptop", ip="10.201.0.2")
        self.assertError("two peers have this name")
        self.assertError("is already another peer's")

    def test_peer_named_like_router(self):
        add_vpn(self.configs)
        self.vpn()["peers"][0]["name"] = "router"
        self.assertError("a peer can't have the router's name")

    def test_bad_key(self):
        add_vpn(self.configs)
        self.vpn()["peers"][1]["public_key"] = "not-a-key"
        self.assertError("public_key must be a WireGuard public key")

    def test_port_clashes_with_udp_forward(self):
        add_vpn(self.configs)
        host(self.configs, "lab", "postgres")["expose"].append({"name": "wg", "proto": "udp", "port": 51820})
        self.assertError("udp/51820 is already forwarded to postgres")

    def test_unknown_key_and_endpoint_with_port(self):
        add_vpn(self.configs, endpoint="vpn.example.com:51820", dns="1.1.1.1")
        self.assertError("unknown setting dns")
        self.assertError("endpoint must be a host name or address, without a port")


if __name__ == "__main__":
    unittest.main()
