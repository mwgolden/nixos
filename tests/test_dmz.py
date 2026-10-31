"""Tests for a network's DMZ: validation, the inventory it gives, and the
checks that use it.

    .venv/bin/python -m unittest discover -s tests
"""

import unittest

from test_derived import add_vpn, host, inventory
from test_network_config import TEMPLATE_IP, TEMPLATE_VM_ID, load_networks, network_config as nc

DMZ = {"bridge": "vmbr7", "cidr": "10.1.1.0/24", "gateway": "10.1.1.1"}


def add_dmz(configs, **extra):
    """lab with a DMZ, a proxy in it, and gitea on the LAN behind it."""
    configs["lab"]["network"]["dmz"] = dict(DMZ, **extra)
    configs["lab"]["hosts"] += [
        {"name": "proxy", "type": "proxy", "zone": "dmz", "vm_id": 116, "ip": "10.1.1.10"},
        {"name": "forge", "type": "gitea", "vm_id": 140, "ip": "10.1.0.14",
         "data_disk": {"size_gb": 40, "storage": "local-lvm"},
         "proxy": [{"name": "git", "port": 3000, "external": True}]},
    ]


class Validation(unittest.TestCase):
    def setUp(self):
        self.files = load_networks()
        self.configs = {f["file"]: f["config"] for f in self.files}
        add_dmz(self.configs)

    def errors(self):
        return nc.network_config_errors(self.files, TEMPLATE_VM_ID, TEMPLATE_IP)

    def warnings(self):
        return nc.network_config_warnings(self.files, TEMPLATE_VM_ID, TEMPLATE_IP)

    def assertError(self, fragment):
        found = self.errors()
        self.assertTrue(any(fragment in e for e in found), f"no error containing {fragment!r} in {found}")

    def test_valid(self):
        self.assertEqual(self.errors(), [])

    def test_dmz_on_home_network(self):
        self.configs["home"]["network"]["dmz"] = {"bridge": "vmbr8", "cidr": "10.9.0.0/24", "gateway": "10.9.0.1"}
        self.assertError("dmz is only used on isolated networks")

    def test_bridge_shared_with_a_network(self):
        self.configs["lab"]["network"]["dmz"]["bridge"] = "vmbr1"
        self.assertError("bridge vmbr1 is already used")

    def test_subnet_overlaps_lan(self):
        self.configs["lab"]["network"]["dmz"]["cidr"] = "10.1.0.0/25"
        self.assertError("dmz.cidr 10.1.0.0/25 overlaps")

    def test_gateway_outside_subnet(self):
        self.configs["lab"]["network"]["dmz"]["gateway"] = "10.1.0.200"
        self.assertError("dmz.gateway 10.1.0.200 is not a usable address")

    def test_unknown_key(self):
        self.configs["lab"]["network"]["dmz"]["nameserver"] = "10.1.1.1"
        self.assertError("unknown setting dmz.nameserver")

    def test_dhcp_range_checked(self):
        self.configs["lab"]["network"]["dmz"]["dhcp"] = {"start": "10.1.1.100", "end": "10.1.1.50"}
        self.assertError("comes after dhcp.end")

    def test_host_ip_must_be_in_its_zone(self):
        host(self.configs, "lab", "proxy")["ip"] = "10.1.0.10"
        self.assertError("10.1.0.10 is not a usable address in lab DMZ's 10.1.1.0/24")

    def test_host_cant_use_the_dmz_gateway(self):
        host(self.configs, "lab", "proxy")["ip"] = "10.1.1.1"
        self.assertError("address 10.1.1.1 is already used")

    def test_zone_without_dmz(self):
        del self.configs["lab"]["network"]["dmz"]
        self.assertError("zone dmz needs a dmz: block")

    def test_unknown_zone(self):
        host(self.configs, "lab", "proxy")["zone"] = "public"
        self.assertError("zone must be lan or dmz")

    def test_router_has_no_zone(self):
        host(self.configs, "lab", "router")["zone"] = "dmz"
        self.assertError("a router can't have a zone")

    def test_reach_only_from_dmz(self):
        host(self.configs, "lab", "forge")["reach"] = [{"host": "postgres", "port": 5432}]
        self.assertError("reach is only used on hosts with zone: dmz")

    def test_reach_unknown_host(self):
        host(self.configs, "lab", "proxy")["reach"] = [{"host": "nope", "port": 5432}]
        self.assertError("host must be a host of network lab, not 'nope'")

    def test_reach_router(self):
        host(self.configs, "lab", "proxy")["reach"] = [{"host": "router", "port": 22}]
        self.assertError("router isn't a LAN host")

    def test_reach_bad_port(self):
        host(self.configs, "lab", "proxy")["reach"] = [{"host": "postgres", "port": 0}]
        self.assertError("port must be from 1 to 65535")

    def test_warns_about_exposed_lan_hosts(self):
        # postgres in the fixture has expose: 5432 and stays on the LAN.
        found = self.warnings()
        self.assertEqual(len(found), 1)
        self.assertIn("host postgres (network lab): has expose: entries but is on the LAN", found[0])

    def test_warns_about_external_proxy_on_lan(self):
        proxy = host(self.configs, "lab", "proxy")
        proxy["zone"] = "lan"
        proxy["ip"] = "10.1.0.10"
        self.assertTrue(any("serves external routes (git) but is on the LAN" in w for w in self.warnings()))

    def test_no_warnings_without_dmz(self):
        files = load_networks()
        self.assertEqual(nc.network_config_warnings(files, TEMPLATE_VM_ID, TEMPLATE_IP), [])

    def test_proxmox_dmz_bridge_must_be_isolated(self):
        ifaces = [{"iface": "vmbr0", "type": "bridge", "bridge_ports": "eno1"},
                  {"iface": "vmbr7", "type": "bridge", "bridge_ports": "eno2"}]
        found = nc.network_config_proxmox_errors(self.configs, [{"vmid": TEMPLATE_VM_ID, "name": "t"}],
                                                 ifaces, TEMPLATE_VM_ID, "pve")
        self.assertEqual(found, ["network lab: vmbr7 exists but is not an isolated bridge "
                                 "(type bridge, ports 'eno2', address '')."])


class Inventory(unittest.TestCase):
    def setUp(self):
        self.inv = inventory(add_dmz)
        self.lab = self.inv["networks"]["lab"]

    def test_network_dmz(self):
        self.assertEqual(self.lab["dmz"], {"bridge": "vmbr7", "cidr": "10.1.1.0/24", "prefix_length": 24,
                                           "gateway": "10.1.1.1", "nameserver": "10.1.1.1", "dhcp": {}})

    def test_no_dmz(self):
        lab = inventory()["networks"]["lab"]
        self.assertEqual((lab["dmz"], lab["dmz_rules"]), ({}, []))

    def test_dmz_host_attaches_to_the_dmz_bridge(self):
        self.assertEqual(self.inv["hosts"]["proxy"]["attach"], {
            "network": "lab", "zone": "dmz", "bridge": "vmbr7", "ip": "10.1.1.10", "prefix_length": 24,
            "gateway": "10.1.1.1", "nameserver": "10.1.1.1", "via_router": "router"})

    def test_router_gets_a_dmz_card(self):
        self.assertEqual(self.inv["hosts"]["router"]["nics"], [
            {"interface": "net1", "bridge": "vmbr1"}, {"interface": "net2", "bridge": "vmbr7"}])

    def test_rule_derived_from_proxy_route(self):
        self.assertEqual(self.lab["dmz_rules"], [
            {"name": "proxy to forge tcp/3000 (proxy route git)", "src_host": "proxy", "src_ip": "10.1.1.10",
             "dst_host": "forge", "dst_ip": "10.1.0.14", "proto": "tcp", "port": 3000}])

    def test_reach_adds_rules_without_duplicates(self):
        def mutate(configs):
            add_dmz(configs)
            host(configs, "lab", "proxy")["reach"] = [
                {"host": "forge", "port": 3000}, {"host": "postgres", "port": 5432}]
        rules = inventory(mutate)["networks"]["lab"]["dmz_rules"]
        self.assertEqual([(r["dst_host"], r["port"]) for r in rules], [("forge", 3000), ("postgres", 5432)])

    def test_no_rule_for_a_backend_in_the_dmz(self):
        def mutate(configs):
            add_dmz(configs)
            gitea = host(configs, "lab", "forge")
            gitea["zone"], gitea["ip"] = "dmz", "10.1.1.14"
        self.assertEqual(inventory(mutate)["networks"]["lab"]["dmz_rules"], [])

    def test_no_rule_for_a_proxy_on_the_lan(self):
        def mutate(configs):
            add_dmz(configs)
            proxy = host(configs, "lab", "proxy")
            proxy["zone"], proxy["ip"] = "lan", "10.1.0.10"
        self.assertEqual(inventory(mutate)["networks"]["lab"]["dmz_rules"], [])

    def test_forwards_carry_the_zone(self):
        zones = {f["name"]: f["zone"] for f in self.lab["port_forwards"]}
        self.assertEqual(zones, {"postgres": "lan", "proxy-https": "dmz", "proxy-http": "dmz"})

    def test_dmz_hosts_get_dns_names(self):
        self.assertIn({"name": "proxy", "fqdn": "proxy.lab.home.arpa", "ip": "10.1.1.10"}, self.lab["dns_records"])
        # Routes point at the proxy's DMZ address.
        self.assertIn({"name": "git", "fqdn": "git.lab.home.arpa", "ip": "10.1.1.10"}, self.lab["dns_records"])

    def test_internal_routes_exclude_the_dmz(self):
        self.assertEqual(self.lab["proxy_internal_sources"], ["10.1.0.0/24", "127.0.0.0/8"])

    def test_vpn_routes_the_dmz(self):
        def mutate(configs):
            add_dmz(configs)
            add_vpn(configs)
        vpn = inventory(mutate)["networks"]["lab"]["vpn"]
        self.assertEqual(vpn["allowed_ips"], ["10.1.0.0/24", "10.1.1.0/24", "10.201.0.0/24"])

    def test_client_networks_add_dmz_sources(self):
        def mutate(configs):
            add_dmz(configs)
            host(configs, "lab", "proxy")["reach"] = [{"host": "postgres", "port": 5432}]
        inv = inventory(mutate)
        # postgres also has expose:, so home is in there too.
        self.assertEqual(nc.host_client_networks(inv["hosts"]["postgres"], inv),
                         ["10.1.0.0/24", "10.1.1.10/32", "192.168.1.0/24"])

    def test_client_networks_of_a_dmz_host(self):
        self.assertEqual(nc.host_client_networks(self.inv["hosts"]["proxy"], self.inv),
                         ["10.1.1.0/24", "10.1.0.0/24"])


class Placement(unittest.TestCase):
    def test_moving_to_the_dmz_goes_through_the_router(self):
        inv = inventory(add_dmz)
        vm = inv["hosts"]["proxy"]
        notes = "nixlab-address: 10.1.0.10 on vmbr1"
        found = nc.placement_candidates(vm, inv, "virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr1", notes,
                                        False, "192.168.1.10", "vmbr0")
        self.assertEqual([(c["ip"], c["bridge"], c["via_router"]) for c in found], [
            ("10.1.0.10", "vmbr1", "router"), ("10.1.1.10", "vmbr7", "router")])


class Checks(unittest.TestCase):
    def setUp(self):
        self.inv = inventory(add_dmz)

    def test_dmz_host_must_not_reach_lan_ssh(self):
        targets = nc.blocked_targets(self.inv["hosts"]["proxy"], self.inv, "")
        self.assertEqual([t["name"] for t in targets if t["port"] == 22],
                         ["LAN host postgres", "LAN host forge"])

    def test_lan_host_has_no_extra_blocked_targets(self):
        targets = nc.blocked_targets(self.inv["hosts"]["forge"], self.inv, "")
        self.assertEqual([t["name"] for t in targets], ["home's gateway"])

    def test_other_networks_dmz_gateway_is_blocked(self):
        def mutate(configs):
            add_dmz(configs)
            configs["other"] = {
                "network": {"name": "other", "type": "isolated", "bridge": "vmbr5", "cidr": "10.5.0.0/24",
                            "gateway": "10.5.0.1", "nameserver": "10.5.0.1", "upstream": "home"},
                "hosts": [{"name": "other-web", "type": "webserver", "vm_id": 501, "ip": "10.5.0.11"}]}
        inv = inventory(mutate)
        names = [t["name"] for t in nc.blocked_targets(inv["hosts"]["other-web"], inv, "")]
        self.assertIn("lab's DMZ gateway", names)

    def test_reachable_from_lan(self):
        self.assertEqual(nc.reachable_targets(self.inv["hosts"]["forge"], self.inv), [
            {"name": "DMZ host proxy", "host": "10.1.1.10", "port": 22}])

    def test_reachable_from_dmz(self):
        self.assertEqual(nc.reachable_targets(self.inv["hosts"]["proxy"], self.inv), [
            {"name": "forge (proxy to forge tcp/3000 (proxy route git))", "host": "10.1.0.14", "port": 3000}])

    def test_nothing_reachable_without_dmz(self):
        inv = inventory()
        self.assertEqual(nc.reachable_targets(inv["hosts"]["postgres"], inv), [])

    def test_proxmox_checks_the_dmz_card(self):
        vms = [{"vmid": 113, "status": "running",
                "config": {"net0": "virtio=A,bridge=vmbr0", "net1": "virtio=B,bridge=vmbr1"}}]
        self.assertEqual(nc.network_verify_proxmox(self.inv, ["router"], vms),
                         {"router": ["net2 is on no bridge, not vmbr7."]})


if __name__ == "__main__":
    unittest.main()
