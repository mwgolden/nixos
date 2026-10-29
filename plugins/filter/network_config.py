"""Checks the network files in networks/ before anything is deployed.

Used from roles/network_config:

    {{ network_files | network_config_errors(template_vm_id, template_ip) }}

network_files is a list of {"file": <name without .yaml>, "config": <parsed
YAML>}. The result is a list of error messages, empty when every file is
valid. All files are checked together, because names, VM IDs, addresses,
bridges and subnets must be unique across networks.
"""

import ipaddress
import re

NETWORK_TYPES = ("home", "isolated")
HOST_TYPES = ("webserver", "postgres", "gitea", "garage", "router", "proxy", "ldap")
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
PORT_FORWARD_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")
LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$")
# Used when a network sets no domain. home.arpa is reserved for local
# networks (RFC 8375), so these names never clash with real ones.
DEFAULT_DOMAIN_SUFFIX = "home.arpa"

NETWORK_KEYS = {"name", "type", "bridge", "cidr", "gateway", "nameserver",
                "upstream", "dhcp", "reserved", "domain"}
HOST_KEYS = {"name", "type", "vm_id", "ip", "wan_ip", "full_clone",
             "data_disk", "settings", "expose", "proxy"}
EXPOSE_KEYS = {"name", "proto", "port", "wan_port"}
PROXY_KEYS = {"name", "port", "external"}
# Router ports forwarded to the proxy when a route on its network is external.
EXTERNAL_PROXY_PORTS = (("https", 443), ("http", 80))
VPN_KEYS = {"cidr", "port", "endpoint", "peers"}
VPN_PEER_KEYS = {"name", "ip", "public_key"}
WG_KEY_RE = re.compile(r"^[A-Za-z0-9+/]{42}[AEIMQUYcgkosw480]=$")
DEFAULT_VPN_PORT = 51820


def network_domain(net):
    """A network's DNS domain: its domain setting, or <name>.home.arpa."""
    return net.get("domain") or f"{net['name']}.{DEFAULT_DOMAIN_SUFFIX}"


def _expose_entries(host):
    """A host's expose: entries with the defaults filled in."""
    entries = []
    for e in host.get("expose") or []:
        port = _int(e.get("port"))
        entries.append({
            # The forward's name, as the router reports it.
            "name": f"{host['name']}-{e['name']}" if e.get("name") else host["name"],
            "proto": e.get("proto", "tcp"),
            "port": port,
            "wan_port": _int(e.get("wan_port", port)),
        })
    return entries


def _addr(value):
    try:
        return ipaddress.IPv4Address(str(value))
    except ValueError:
        return None


def _net(value):
    try:
        return ipaddress.IPv4Network(str(value), strict=True)
    except ValueError:
        return None


def _int(value):
    if isinstance(value, bool):
        return None
    try:
        return int(str(value))
    except ValueError:
        return None


class _Checker:
    def __init__(self, template_vm_id, template_ip):
        self.errors = []
        self.template_vm_id = _int(template_vm_id)
        self.template_ip = _addr(template_ip)
        # Values that must be unique across every network:
        # value -> "where it was first seen".
        self.names = {}
        self.vm_ids = {}
        self.addresses = {}
        self.bridges = {}
        self.domains = {}
        # Per network: forward name -> host, (proto, wan_port) -> host.
        self.forward_names = {}
        self.forward_ports = {}
        # Per network: route name -> host that asked for it.
        self.routes = {}
        # Per network: names of external routes.
        self.external_routes = {}
        self.cidrs = []  # (network, where)
        # Parsed networks by name, for upstream and WAN checks.
        self.networks = {}

    def error(self, where, message):
        self.errors.append(f"{where}: {message}")

    def unique(self, seen, value, where, what):
        if value in seen:
            self.error(where, f"{what} {value} is already used by {seen[value]}.")
        else:
            seen[value] = where

    # Network block

    def check_network(self, file, config):
        where = f"networks/{file}.yaml"
        if not isinstance(config, dict) or not isinstance(config.get("network"), dict):
            self.error(where, "needs a 'network:' block.")
            return None
        net = config["network"]
        for key in sorted(set(net) - NETWORK_KEYS):
            self.error(where, f"unknown setting network.{key}.")

        name = net.get("name")
        if name != file:
            self.error(where, f"network.name must be '{file}', the file's name, not '{name}'.")
        if not isinstance(name, str) or not NAME_RE.match(name):
            self.error(where, "network.name must be lowercase letters, digits and '-', starting with a letter.")
            return None
        where = f"network {name}"

        kind = net.get("type")
        if kind not in NETWORK_TYPES:
            self.error(where, f"type must be one of {', '.join(NETWORK_TYPES)}, not '{kind}'.")

        bridge = net.get("bridge")
        if not isinstance(bridge, str) or not re.match(r"^vmbr[0-9]+$", bridge):
            self.error(where, f"bridge must be a Proxmox bridge name like vmbr1, not '{bridge}'.")
        else:
            self.unique(self.bridges, bridge, where, "bridge")

        cidr = _net(net.get("cidr"))
        if cidr is None:
            self.error(where, f"cidr must be an IPv4 network like 10.1.0.0/24 (host bits zero), not '{net.get('cidr')}'.")
        else:
            for other, other_where in self.cidrs:
                if cidr.overlaps(other):
                    self.error(where, f"cidr {cidr} overlaps {other} of {other_where}.")
            self.cidrs.append((cidr, where))

        domain = net.get("domain")
        if domain is not None and (not isinstance(domain, str) or not DOMAIN_RE.match(domain)):
            self.error(where, f"domain must be a DNS name like lab.home.arpa (lowercase), not '{domain}'.")
        else:
            self.unique(self.domains, network_domain(net), where, "domain")

        parsed = {"name": name, "type": kind, "bridge": bridge, "cidr": cidr,
                  "domain": network_domain(net),
                  "where": where, "reserved": set(), "dhcp": None,
                  "upstream": net.get("upstream")}

        for key in ("gateway", "nameserver"):
            addr = _addr(net.get(key))
            if addr is None:
                self.error(where, f"{key} must be an IPv4 address, not '{net.get(key)}'.")
            elif key == "gateway":
                parsed["gateway"] = addr
                if cidr is not None and not self.usable(cidr, addr):
                    self.error(where, f"gateway {addr} is not a usable address in {cidr}.")

        reserved = net.get("reserved", [])
        if not isinstance(reserved, list):
            self.error(where, "reserved must be a list of addresses.")
            reserved = []
        for item in reserved:
            addr = _addr(item)
            if addr is None:
                self.error(where, f"reserved address '{item}' is not an IPv4 address.")
            else:
                parsed["reserved"].add(addr)

        dhcp = net.get("dhcp")
        if dhcp is not None:
            parsed["dhcp"] = self.check_dhcp(where, dhcp, cidr)
        elif kind == "isolated":
            self.error(where, "an isolated network needs a dhcp block: its router serves DHCP.")

        if kind == "isolated":
            if not isinstance(parsed["upstream"], str):
                self.error(where, "an isolated network needs upstream: the name of the network its router's WAN side is on.")
        elif parsed["upstream"] is not None:
            self.error(where, "upstream is only used by isolated networks.")

        self.networks[name] = parsed
        return parsed

    def check_dhcp(self, where, dhcp, cidr):
        if not isinstance(dhcp, dict):
            self.error(where, "dhcp must have start, end and lease_time.")
            return None
        start, end = _addr(dhcp.get("start")), _addr(dhcp.get("end"))
        if start is None or end is None:
            self.error(where, "dhcp.start and dhcp.end must be IPv4 addresses.")
            return None
        if start > end:
            self.error(where, f"dhcp.start {start} comes after dhcp.end {end}.")
        if cidr is not None and not (self.usable(cidr, start) and self.usable(cidr, end)):
            self.error(where, f"the DHCP range {start}-{end} must be inside {cidr}.")
        lease = dhcp.get("lease_time", "12h")
        if not re.match(r"^[0-9]+[smhd]?$|^infinite$", str(lease)):
            self.error(where, f"dhcp.lease_time '{lease}' must be like 12h, 30m or infinite.")
        return (start, end)

    @staticmethod
    def usable(cidr, addr):
        return addr in cidr and addr not in (cidr.network_address, cidr.broadcast_address)

    # Hosts

    def check_hosts(self, net, config):
        hosts = config.get("hosts", [])
        if not isinstance(hosts, list):
            self.error(net["where"], "hosts must be a list.")
            return []
        routers = [h for h in hosts if isinstance(h, dict) and h.get("type") == "router"]
        if net["type"] == "isolated" and len(routers) != 1:
            self.error(net["where"], f"an isolated network needs exactly one host of type router, not {len(routers)}.")
        if net["type"] == "home" and routers:
            self.error(net["where"], "a home network can't have a router host; the home router is outside this project.")
        for host in hosts:
            self.check_host(net, host)
        return hosts

    def check_host(self, net, host):
        if not isinstance(host, dict):
            self.error(net["where"], f"host entry {host!r} must be a mapping.")
            return
        name = host.get("name")
        where = f"host {name} (network {net['name']})"
        if not isinstance(name, str) or not NAME_RE.match(name):
            self.error(net["where"], f"host name '{name}' must be lowercase letters, digits and '-', starting with a letter.")
            return
        self.unique(self.names, name, where, "host name")
        for key in sorted(set(host) - HOST_KEYS):
            self.error(where, f"unknown setting {key}. Type-specific settings go under settings:.")

        kind = host.get("type")
        if kind not in HOST_TYPES:
            self.error(where, f"type must be one of {', '.join(HOST_TYPES)}, not '{kind}'.")

        vm_id = _int(host.get("vm_id"))
        if vm_id is None or not 100 <= vm_id <= 999999999:
            self.error(where, f"vm_id must be a number from 100 to 999999999, not '{host.get('vm_id')}'.")
        elif vm_id == self.template_vm_id:
            self.error(where, f"vm_id {vm_id} is the template's ID.")
        else:
            self.unique(self.vm_ids, vm_id, where, "vm_id")

        ip = _addr(host.get("ip"))
        if ip is None:
            self.error(where, f"ip must be an IPv4 address, not '{host.get('ip')}'.")
        else:
            self.check_address(net, where, "ip", ip, is_router=(kind == "router"))

        if kind == "router":
            wan_ip = _addr(host.get("wan_ip"))
            if wan_ip is None:
                self.error(where, f"a router needs wan_ip, its address on the upstream network, not '{host.get('wan_ip')}'.")
            else:
                upstream = self.networks.get(net["upstream"])
                if upstream is None:
                    # Reported once the upstream is known to be missing.
                    self.pending_wan.append((net, where, wan_ip))
                else:
                    self.check_address(upstream, where, "wan_ip", wan_ip)
            settings = host.get("settings")
            if isinstance(settings, dict) and "port_forwards" in settings:
                self.error(where, "settings.port_forwards has been replaced by expose: on the hosts the ports go to. "
                                  "See networks/README.md.")
            if isinstance(settings, dict) and settings.get("vpn") is not None:
                self.check_vpn(net, where, settings["vpn"], name)
        elif "wan_ip" in host:
            self.error(where, "wan_ip is only used by routers.")

        if "full_clone" in host and not isinstance(host["full_clone"], bool):
            self.error(where, "full_clone must be true or false.")

        disk = host.get("data_disk")
        if disk is not None:
            size = _int(disk.get("size_gb")) if isinstance(disk, dict) else None
            if size is None or size < 1:
                self.error(where, "data_disk.size_gb must be a whole number of GB, at least 1.")
            if not isinstance(disk, dict) or not isinstance(disk.get("storage"), str):
                self.error(where, "data_disk.storage must name a Proxmox storage, like local-lvm.")
        elif kind in ("postgres", "gitea", "garage"):
            self.error(where, f"a {kind} host needs a data_disk with size_gb and storage.")

        if not isinstance(host.get("settings", {}), dict):
            self.error(where, "settings must be a mapping.")
        elif kind == "postgres":
            self.check_allowed_networks(where, host.get("settings") or {})

        if "expose" in host:
            self.check_expose(net, where, host, kind)
        if "proxy" in host:
            self.check_proxy_routes(net, where, host, kind)

    def check_address(self, net, where, key, ip, is_router=False):
        cidr = net["cidr"]
        if cidr is not None and not self.usable(cidr, ip):
            self.error(where, f"{key} {ip} is not a usable address in {net['name']}'s {cidr}.")
        if is_router:
            if ip != net.get("gateway"):
                self.error(where, f"a router's ip must be its network's gateway ({net.get('gateway')}), not {ip}.")
        elif ip == net.get("gateway"):
            self.error(where, f"{key} {ip} is {net['name']}'s gateway.")
        if ip == self.template_ip:
            self.error(where, f"{key} {ip} is the template's address (template_ip in proxmox/vars.yaml).")
        if ip in net["reserved"]:
            self.error(where, f"{key} {ip} is reserved in network {net['name']}.")
        if net["dhcp"] and net["dhcp"][0] <= ip <= net["dhcp"][1]:
            self.error(where, f"{key} {ip} is inside {net['name']}'s DHCP range {net['dhcp'][0]}-{net['dhcp'][1]}.")
        self.unique(self.addresses, ip, where, "address")

    def check_expose(self, net, where, host, kind):
        expose = host.get("expose")
        if not isinstance(expose, list):
            self.error(where, "expose must be a list.")
            return
        if net["type"] != "isolated":
            self.error(where, "expose is only used on isolated networks; hosts on a home network are reached directly.")
            return
        if kind == "router":
            self.error(where, "a router can't expose ports; expose: goes on the hosts the ports are forwarded to.")
            return
        names = self.forward_names.setdefault(net["name"], {})
        ports = self.forward_ports.setdefault(net["name"], {})
        for entry in expose:
            if not isinstance(entry, dict):
                self.error(where, f"expose entry {entry!r} must be a mapping.")
                continue
            label = f"expose entry {entry.get('name') or entry.get('port')}"
            for key in sorted(set(entry) - EXPOSE_KEYS):
                self.error(where, f"{label}: unknown setting {key}.")
            if "name" in entry and not PORT_FORWARD_NAME_RE.match(str(entry["name"])):
                self.error(where, f"{label}: name must be letters, digits, '-' and '_'.")
            proto = entry.get("proto", "tcp")
            if proto not in ("tcp", "udp"):
                self.error(where, f"{label}: proto must be tcp or udp.")
            port = _int(entry.get("port"))
            wan_port = _int(entry.get("wan_port", entry.get("port")))
            for key, value in (("port", port), ("wan_port", wan_port)):
                if value is None or not 1 <= value <= 65535:
                    self.error(where, f"{label}: {key} must be from 1 to 65535.")
            if proto == "tcp" and wan_port == 22:
                self.error(where, f"{label}: TCP 22 on the router can't be forwarded; it is the router's own SSH. Set wan_port.")
            forward = f"{host['name']}-{entry['name']}" if entry.get("name") else host["name"]
            if forward in names:
                self.error(where, f"{label}: forward name '{forward}' is already used. Give each entry its own name.")
            names[forward] = host["name"]
            if (proto, wan_port) in ports:
                self.error(where, f"{label}: the router's {proto}/{wan_port} is already forwarded to {ports[(proto, wan_port)]}.")
            ports[(proto, wan_port)] = host["name"]

    def check_proxy_routes(self, net, where, host, kind):
        routes = host.get("proxy")
        if not isinstance(routes, list):
            self.error(where, "proxy must be a list.")
            return
        if kind in ("proxy", "router"):
            self.error(where, f"a {kind} host can't have proxy: routes; they go on the hosts the proxy sends requests to.")
            return
        seen = self.routes.setdefault(net["name"], {})
        for route in routes:
            if not isinstance(route, dict):
                self.error(where, f"proxy entry {route!r} must be a mapping.")
                continue
            name = route.get("name")
            label = f"proxy route '{name}'"
            for key in sorted(set(route) - PROXY_KEYS):
                self.error(where, f"{label}: unknown setting {key}.")
            if not isinstance(name, str) or not LABEL_RE.match(name):
                self.error(where, f"{label}: name must be one DNS label (lowercase letters, digits and '-'), "
                                  f"such as git; it is served as <name>.{net['domain']}.")
            port = _int(route.get("port"))
            if port is None or not 1 <= port <= 65535:
                self.error(where, f"{label}: port must be from 1 to 65535.")
            if name in seen:
                self.error(where, f"{label}: the name is already a route to {seen[name]}.")
            seen[name] = host["name"]
            external = route.get("external", False)
            if not isinstance(external, bool):
                self.error(where, f"{label}: external must be true or false.")
            elif external and net["type"] != "isolated":
                self.error(where, f"{label}: external is only used on isolated networks; "
                                  "on a home network the whole LAN already reaches the proxy.")
            elif external:
                self.external_routes.setdefault(net["name"], []).append(name)

    def check_vpn(self, net, where, vpn, router_name):
        if not isinstance(vpn, dict):
            self.error(where, "settings.vpn must be a mapping with cidr and peers.")
            return
        for key in sorted(set(vpn) - VPN_KEYS):
            self.error(where, f"settings.vpn: unknown setting {key}.")
        cidr = _net(vpn.get("cidr"))
        if cidr is None:
            self.error(where, f"settings.vpn.cidr must be a subnet like 10.201.0.0/24 (host bits zero), not '{vpn.get('cidr')}'.")
        else:
            for other, other_where in self.cidrs:
                if cidr.overlaps(other):
                    self.error(where, f"settings.vpn.cidr {cidr} overlaps {other} of {other_where}.")
            self.cidrs.append((cidr, f"{where}'s VPN"))
        port = _int(vpn.get("port", DEFAULT_VPN_PORT))
        if port is None or not 1 <= port <= 65535:
            self.error(where, "settings.vpn.port must be from 1 to 65535.")
        else:
            self.pending_vpn_ports.append((net, where, port))
        endpoint = vpn.get("endpoint", "")
        if not isinstance(endpoint, str) or not re.match(r"^[A-Za-z0-9.-]*$", endpoint):
            self.error(where, "settings.vpn.endpoint must be a host name or address, without a port.")
        peers = vpn.get("peers", [])
        if not isinstance(peers, list):
            self.error(where, "settings.vpn.peers must be a list.")
            return
        names, ips = set(), set()
        router_address = next(cidr.hosts()) if cidr is not None else None
        for peer in peers:
            if not isinstance(peer, dict):
                self.error(where, f"VPN peer {peer!r} must be a mapping.")
                continue
            label = f"VPN peer '{peer.get('name')}'"
            for key in sorted(set(peer) - VPN_PEER_KEYS):
                self.error(where, f"{label}: unknown setting {key}.")
            name = peer.get("name")
            if not isinstance(name, str) or not LABEL_RE.match(name):
                self.error(where, f"{label}: name must be lowercase letters, digits and '-'.")
            elif name in names:
                self.error(where, f"{label}: two peers have this name.")
            elif name == router_name:
                self.error(where, f"{label}: a peer can't have the router's name; their keys would share a file.")
            names.add(name)
            ip = _addr(peer.get("ip"))
            if ip is None or cidr is None or not self.usable(cidr, ip):
                self.error(where, f"{label}: ip must be a usable address in settings.vpn.cidr.")
            elif ip == router_address:
                self.error(where, f"{label}: {ip} is the router's own VPN address.")
            elif ip in ips:
                self.error(where, f"{label}: {ip} is already another peer's.")
            ips.add(ip)
            key = peer.get("public_key")
            if key is not None and not (isinstance(key, str) and WG_KEY_RE.match(key)):
                self.error(where, f"{label}: public_key must be a WireGuard public key (44 characters ending in '=').")

    def check_allowed_networks(self, where, settings):
        allowed = settings.get("allowed_networks")
        if allowed is None:
            return
        if not isinstance(allowed, list):
            self.error(where, "settings.allowed_networks must be a list of network names or subnets.")
            return
        for item in allowed:
            if not (str(item) in self.networks or _net(item) is not None):
                self.error(where, f"settings.allowed_networks: '{item}' is neither a network in networks/ "
                                  "nor a subnet like 10.1.0.0/24 (host bits zero).")

    # Driver

    def run(self, network_files):
        self.pending_wan = []
        self.pending_vpn_ports = []
        parsed = []
        # Networks first, so hosts can check against any network's settings.
        for item in network_files:
            net = self.check_network(item["file"], item["config"])
            if net is not None:
                parsed.append((net, item["config"]))
        for net, config in parsed:
            if net["type"] == "isolated" and isinstance(net["upstream"], str):
                upstream = self.networks.get(net["upstream"])
                if upstream is None:
                    self.error(net["where"], f"upstream '{net['upstream']}' is not a network in networks/.")
                elif upstream["type"] != "home":
                    self.error(net["where"], f"upstream '{net['upstream']}' must be a home network.")
        for net, config in parsed:
            hosts = [h for h in self.check_hosts(net, config) if isinstance(h, dict)]
            proxies = [h.get("name") for h in hosts if h.get("type") == "proxy"]
            if len(proxies) > 1:
                self.error(net["where"], f"a network can have only one proxy host, not {len(proxies)}: {', '.join(proxies)}.")
            routes = self.routes.get(net["name"], {})
            if routes and not proxies:
                self.error(net["where"], f"hosts here have proxy: routes ({', '.join(sorted(routes))}) "
                                         "but the network has no host of type proxy.")
            external = self.external_routes.get(net["name"])
            if external:
                ports = self.forward_ports.get(net["name"], {})
                for _, port in EXTERNAL_PROXY_PORTS:
                    if ("tcp", port) in ports:
                        self.error(net["where"], f"the external proxy routes ({', '.join(external)}) need the router's "
                                                 f"tcp/{port}, which is already forwarded to {ports[('tcp', port)]}.")
            host_names = {h.get("name") for h in hosts}
            for route, owner in routes.items():
                if route in host_names:
                    self.error(f"host {owner} (network {net['name']})",
                               f"proxy route '{route}' has the same name as host {route}; "
                               "both would be the same DNS name.")
        for net, where, port in self.pending_vpn_ports:
            owner = self.forward_ports.get(net["name"], {}).get(("udp", port))
            if owner:
                self.error(where, f"settings.vpn.port {port}: the router's udp/{port} is already forwarded to {owner}.")
        for net, where, wan_ip in self.pending_wan:
            upstream = self.networks.get(net["upstream"])
            if upstream is not None:
                self.check_address(upstream, where, "wan_ip", wan_ip)
        return self.errors


def network_config_errors(network_files, template_vm_id=None, template_ip=None):
    return _Checker(template_vm_id, template_ip).run(network_files)


def network_config_proxmox_errors(network_configs, vms, ifaces, template_vm_id, node):
    """Compares valid network files with what exists in Proxmox.

    network_configs: network name -> parsed file.
    vms: proxmox_vm_info's proxmox_vms. ifaces: proxmox_node_network_info's
    proxmox_node_networks.
    """
    errors = []
    by_id = {int(vm["vmid"]): vm.get("name") for vm in vms}
    by_iface = {i.get("iface"): i for i in ifaces}
    if int(template_vm_id) not in by_id:
        errors.append(f"The template, VM {template_vm_id}, does not exist. Run ./bootstrap.sh first.")
    for name, config in network_configs.items():
        net = config["network"]
        iface = by_iface.get(net["bridge"])
        if net["type"] == "home" and iface is None:
            errors.append(f"network {name}: bridge {net['bridge']} does not exist on {node}.")
        elif net["type"] == "isolated" and iface is not None:
            ports = iface.get("bridge_ports") or ""
            cidr = iface.get("cidr") or ""
            if iface.get("type") != "bridge" or ports not in ("", "none") or cidr:
                errors.append(
                    f"network {name}: {net['bridge']} exists but is not an isolated bridge "
                    f"(type {iface.get('type')}, ports '{ports}', address '{cidr}').")
        for host in config.get("hosts") or []:
            vm_id = int(host["vm_id"])
            found = by_id.get(vm_id)
            if found is not None and found != host["name"]:
                errors.append(f"host {host['name']}: VM {vm_id} exists but is named '{found}'.")
            for other_id, other_name in by_id.items():
                if other_name == host["name"] and other_id != vm_id:
                    errors.append(
                        f"host {host['name']}: a VM with this name already exists as VM {other_id}, "
                        f"not {vm_id}. Fix vm_id, or deploying would create a second VM.")
    return errors


def network_config_summary(network_configs, vms):
    """One line per network: how many of its hosts exist in Proxmox."""
    ids = {int(vm["vmid"]) for vm in vms}
    lines = []
    for name, config in network_configs.items():
        hosts = config.get("hosts") or []
        missing = [h["name"] for h in hosts if int(h["vm_id"]) not in ids]
        line = f"{name}: {len(hosts) - len(missing)} of {len(hosts)} hosts exist"
        if missing:
            line += ", to create: " + ", ".join(missing)
        lines.append(line)
    return lines


def network_config_inventory(network_configs):
    """Turns valid network files into what the deploy playbooks use.

    Returns {"networks": {name: network}, "hosts": {name: vm}} where each vm
    has its declared settings plus:
      network  the network it belongs to
      attach   where its first network card (net0, ens18) sits: the bridge,
               its address there, and the gateway and DNS server it uses.
               For a router that is the upstream network at wan_ip; for
               everything else its own network at ip.
      nics     extra network cards: a router's LAN card on its own bridge
      expose   ports forwarded to it from its router's WAN address
      dns_name its name in its router's DNS server, <name>.<domain>, or ""
               on a home network, which has no DNS server here
    and each network has:
      router         the name of its router host, or ""
      router_wan_ip  that router's upstream address, or ""
      domain         its DNS domain
      dns_records    {name, fqdn, ip} for every host on it, which its
                     router's DNS server answers
      port_forwards  {name, host, proto, wan_port, lan_ip, lan_port} built
                     from its hosts' expose: entries, for its router
      vpn            its router's WireGuard VPN, or {}: cidr, prefix_length,
                     address (the router's), port, endpoint, peers
                     ({name, ip, public_key}; public_key "" means the deploy
                     makes a key pair) and allowed_ips (what clients route
                     through it)
      proxy          the name of its proxy host, or ""
      proxy_routes   {name, fqdn, host, backend_ip, port, external} built
                     from its hosts' proxy: entries, for its proxy. Their
                     names are also in dns_records, at the proxy's address.
                     When any is external, port_forwards also sends the
                     router's tcp 443 and 80 to the proxy.
      proxy_internal_sources
                     subnets allowed to use routes that aren't external:
                     the network's, its VPN's and the proxy's own loopback
    """
    networks = {}
    for name, config in network_configs.items():
        net = config["network"]
        cidr = ipaddress.IPv4Network(str(net["cidr"]))
        router = next((h["name"] for h in config.get("hosts") or [] if h["type"] == "router"), "")
        networks[name] = {
            "name": name,
            "type": net["type"],
            "bridge": net["bridge"],
            "cidr": str(cidr),
            "prefix_length": cidr.prefixlen,
            "gateway": str(net["gateway"]),
            "nameserver": str(net["nameserver"]),
            "upstream": net.get("upstream", ""),
            "dhcp": net.get("dhcp") or {},
            "router": router,
            "router_wan_ip": "",
            "domain": network_domain(net),
            "dns_records": [],
            "port_forwards": [],
            "proxy": next((h["name"] for h in config.get("hosts") or [] if h["type"] == "proxy"), ""),
            "proxy_routes": [],
            "proxy_internal_sources": [],
            "vpn": {},
        }
    for name, config in network_configs.items():
        for h in config.get("hosts") or []:
            if h["type"] == "router":
                networks[name]["router_wan_ip"] = str(h["wan_ip"])
                vpn = (h.get("settings") or {}).get("vpn")
                if vpn:
                    networks[name]["vpn"] = _vpn(vpn, networks[name], str(h["wan_ip"]))
            net = networks[name]
            net["dns_records"].append({"name": h["name"], "fqdn": f"{h['name']}.{net['domain']}",
                                       "ip": str(h["ip"])})
            for e in _expose_entries(h):
                net["port_forwards"].append({"name": e["name"], "host": h["name"], "proto": e["proto"],
                                             "wan_port": e["wan_port"], "lan_ip": str(h["ip"]),
                                             "lan_port": e["port"]})
            for r in h.get("proxy") or []:
                net["proxy_routes"].append({"name": r["name"], "fqdn": f"{r['name']}.{net['domain']}",
                                            "host": h["name"], "backend_ip": str(h["ip"]),
                                            "port": int(r["port"]),
                                            "external": bool(r.get("external", False))})
        net = networks[name]
        if net["proxy"]:
            proxy_ip = next(str(h["ip"]) for h in config["hosts"] if h["name"] == net["proxy"])
            for r in net["proxy_routes"]:
                net["dns_records"].append({"name": r["name"], "fqdn": r["fqdn"], "ip": proxy_ip})
            if any(r["external"] for r in net["proxy_routes"]):
                for label, port in EXTERNAL_PROXY_PORTS:
                    net["port_forwards"].append({"name": f"{net['proxy']}-{label}", "host": net["proxy"],
                                                 "proto": "tcp", "wan_port": port, "lan_ip": proxy_ip,
                                                 "lan_port": port})
        net["proxy_internal_sources"] = ([net["cidr"]] + ([net["vpn"]["cidr"]] if net["vpn"] else [])
                                         + ["127.0.0.0/8"])

    hosts = {}
    for name, config in network_configs.items():
        net = networks[name]
        for h in config.get("hosts") or []:
            is_router = h["type"] == "router"
            attach_net = networks[net["upstream"]] if is_router else net
            disk = h.get("data_disk")
            hosts[h["name"]] = {
                "name": h["name"],
                "type": h["type"],
                "vm_id": int(h["vm_id"]),
                "ip": str(h["ip"]),
                "full_clone": bool(h.get("full_clone", False)),
                "settings": h.get("settings") or {},
                # The serial is per type: each type's configuration.nix
                # mounts /dev/disk/by-id/scsi-0QEMU_QEMU_HARDDISK_<type>-data.
                "data_disk": ({"serial": f"{h['type']}-data",
                               "size_gb": int(disk["size_gb"]),
                               "storage": disk["storage"]} if disk else {}),
                "network": net,
                "attach": {
                    "network": attach_net["name"],
                    "bridge": attach_net["bridge"],
                    "ip": str(h["wan_ip"] if is_router else h["ip"]),
                    "prefix_length": attach_net["prefix_length"],
                    "gateway": attach_net["gateway"],
                    "nameserver": attach_net["nameserver"],
                    "via_router": attach_net["router"] if attach_net["type"] == "isolated" else "",
                },
                "nics": [{"interface": "net1", "bridge": net["bridge"]}] if is_router else [],
                "expose": _expose_entries(h),
                "dns_name": f"{h['name']}.{net['domain']}" if net["type"] == "isolated" else "",
            }
    return {"networks": networks, "hosts": hosts}


def _vpn(vpn, net, wan_ip):
    cidr = ipaddress.IPv4Network(str(vpn["cidr"]))
    port = int(vpn.get("port", DEFAULT_VPN_PORT))
    return {
        "cidr": str(cidr),
        "prefix_length": cidr.prefixlen,
        "address": str(next(cidr.hosts())),
        "port": port,
        # Where clients send their packets. The router's WAN address only
        # works from the upstream network.
        "endpoint": f"{vpn.get('endpoint') or wan_ip}:{port}",
        "peers": [{"name": p["name"], "ip": str(p["ip"]), "public_key": p.get("public_key", "")}
                  for p in vpn.get("peers") or []],
        "allowed_ips": [net["cidr"], str(cidr)],
    }


def host_client_networks(vm, inventory):
    """Subnets that can reach a host: its own network's, its router's VPN
    when there is one, and the upstream network's when the host exposes
    ports through its router (forwarded connections keep their upstream
    source address)."""
    net = vm["network"]
    cidrs = [net["cidr"]]
    if net.get("vpn"):
        cidrs.append(net["vpn"]["cidr"])
    if vm.get("expose") and net["type"] == "isolated" and net["upstream"] in inventory["networks"]:
        cidrs.append(inventory["networks"][net["upstream"]]["cidr"])
    return cidrs


def network_cidrs(entries, inventory):
    """entries with each network name replaced by that network's subnet.
    Subnets are kept as they are. Duplicates are dropped."""
    result = []
    for item in entries or []:
        item = str(item)
        cidr = inventory["networks"][item]["cidr"] if item in inventory["networks"] else item
        if cidr not in result:
            result.append(cidr)
    return result


ADDRESS_RE = re.compile(r"^nixlab-address: (\S+) on (\S+)$", re.M)


def recorded_address(description):
    """The address a deploy recorded in a VM's Proxmox notes, or {}."""
    match = ADDRESS_RE.search(description or "")
    return {"ip": match.group(1), "bridge": match.group(2)} if match else {}


DNS_RE = re.compile(r"^nixlab-dns: (\S+)$", re.M)


def recorded_dns_name(description):
    """The DNS name a deploy recorded in a VM's Proxmox notes, or ""."""
    match = DNS_RE.search(description or "")
    return match.group(1) if match else ""


def _set_line(description, pattern, line):
    """description with the line matching pattern replaced by line, or line
    added at the end. An empty line removes the matching one."""
    if pattern.search(description):
        if line:
            return pattern.sub(line, description, count=1)
        return re.sub(r"\n{2,}", "\n", pattern.sub("", description, count=1)).strip("\n")
    if not line:
        return description
    return (description.rstrip("\n") + "\n" + line) if description.strip() else line


def record_address(description, ip, bridge, dns_name=""):
    """The VM's notes with its recorded address set to ip on bridge, and its
    DNS name set to dns_name (or removed, when dns_name is empty).

    Other lines in the notes are kept.
    """
    description = _set_line(description or "", ADDRESS_RE, f"nixlab-address: {ip} on {bridge}")
    return _set_line(description, DNS_RE, f"nixlab-dns: {dns_name}" if dns_name else "")


def placement_candidates(vm, inventory, net0, description, new_clone, template_ip, template_bridge):
    """Where to look for a VM over SSH, in order.

    Each candidate is {ip, bridge, via_router, delay, timeout}. via_router
    names the router to go through ("" for direct). A candidate on another
    bridge than net0's means moving net0 there before looking.
    """
    if new_clone:
        return [_candidate(inventory, template_ip, template_bridge, 5, 300)]

    match = re.search(r"bridge=([^,]+)", net0 or "")
    current_bridge = match.group(1) if match else vm["attach"]["bridge"]
    recorded = recorded_address(description)
    attach = vm["attach"]
    wanted = []
    # Where the last deploy left it.
    if recorded and recorded["bridge"] == current_bridge:
        wanted.append((recorded["ip"], current_bridge, 0, 60))
    # Where it should be, if its card is already on that bridge.
    if attach["bridge"] == current_bridge:
        wanted.append((attach["ip"], current_bridge, 0, 60))
    # A first deploy that stopped before the VM left the template address.
    if current_bridge == template_bridge:
        wanted.append((template_ip, current_bridge, 0, 20))
    # A move that stopped after the address changed but before the card
    # moved, or the other way round.
    if attach["bridge"] != current_bridge:
        wanted.append((attach["ip"], attach["bridge"], 0, 60))
    if recorded and recorded["bridge"] != current_bridge:
        wanted.append((recorded["ip"], recorded["bridge"], 0, 60))

    result, seen = [], set()
    for ip, bridge, delay, timeout in wanted:
        if (ip, bridge) not in seen:
            seen.add((ip, bridge))
            result.append(_candidate(inventory, ip, bridge, delay, timeout))
    return result


def _candidate(inventory, ip, bridge, delay, timeout):
    net = next((n for n in inventory["networks"].values() if n["bridge"] == bridge), None)
    via = net["router"] if net and net["type"] == "isolated" else ""
    return {"ip": ip, "bridge": bridge, "via_router": via, "delay": delay, "timeout": timeout}


def network_config_deploy_order(inventory, network):
    """Names of a network's hosts in the order to deploy them: its router
    first (everything else reaches the network through it), then the rest
    in the order the network file lists them."""
    hosts = [h for h in inventory["hosts"].values() if h["network"]["name"] == network]
    return ([h["name"] for h in hosts if h["type"] == "router"]
            + [h["name"] for h in hosts if h["type"] != "router"])


# Ownership: tags the project puts on the VMs it deploys. Only these kinds
# of tag are ever changed; any others on a VM are kept.
OWNER_TAG = "nixlab"


def _tags(value):
    """Proxmox stores tags as one string, separated by ';' (or ',' or spaces)."""
    return [t for t in re.split(r"[;, ]+", value or "") if t]


def _is_managed_tag(tag):
    return tag == OWNER_TAG or tag.startswith("net-") or tag.startswith("type-")


def nixlab_tags(vm):
    """The tags a deployed VM should carry."""
    return [OWNER_TAG, f"net-{vm['network']['name']}", f"type-{vm['type']}"]


def proxmox_tags_merge(existing, desired):
    """existing (a Proxmox tags string) with the project's own tags replaced
    by desired, keeping every other tag. Returns a Proxmox tags string."""
    others = [t for t in _tags(existing) if not _is_managed_tag(t)]
    return ";".join(others + [t for t in desired if t not in others])


def _vm_summary(vm):
    config = vm.get("config") or {}
    tags = _tags(config.get("tags") or vm.get("tags"))
    kind = next((t[len("type-"):] for t in tags if t.startswith("type-")), "")
    nets = [t[len("net-"):] for t in tags if t.startswith("net-")]
    return {"vmid": int(vm["vmid"]), "name": vm.get("name"), "type": kind,
            "owned": OWNER_TAG in tags, "networks": nets,
            "address": recorded_address(config.get("description"))}


def network_config_ownership(inventory, network, vms):
    """Compares a network's file with the VMs Proxmox has tagged for it.

    vms: proxmox_vm_info's proxmox_vms, with config. Returns
      orphans    VMs tagged for this network that no network file declares:
                 removed from the file. Pruning deletes these.
      moved      VMs tagged for this network but declared in another file,
                 not yet redeployed there. Never pruned.
      untagged   this network's declared hosts that exist with the right ID
                 and name but without the project's tag, because they were
                 deployed before tagging. The next deploy tags them.
      conflicts  orphans still holding an address a declared host uses.
    Each entry is {vmid, name, type, address, ...}.
    """
    declared = {(h["vm_id"], h["name"]): h for h in inventory["hosts"].values()}
    attach_ips = {h["attach"]["ip"]: h["name"] for h in inventory["hosts"].values()}
    result = {"orphans": [], "moved": [], "untagged": [], "conflicts": []}
    for raw in vms:
        vm = _vm_summary(raw)
        host = declared.get((vm["vmid"], vm["name"]))
        if host and host["network"]["name"] == network and not vm["owned"]:
            result["untagged"].append(vm)
        if not (vm["owned"] and network in vm["networks"]):
            continue
        if host is None:
            result["orphans"].append(vm)
            ip = vm["address"].get("ip")
            if ip in attach_ips:
                result["conflicts"].append(dict(vm, used_by=attach_ips[ip]))
        elif host["network"]["name"] != network:
            result["moved"].append(dict(vm, declared_in=host["network"]["name"]))
    return result


def network_config_destroy_order(inventory, network, vms):
    """VMs to delete when destroying a network: every VM tagged for it,
    except ones declared in another network file (moved there). Routers
    last, since the others reach the network through them."""
    declared = {(h["vm_id"], h["name"]): h for h in inventory["hosts"].values()}
    chosen = []
    for raw in vms:
        vm = _vm_summary(raw)
        if not (vm["owned"] and network in vm["networks"]):
            continue
        host = declared.get((vm["vmid"], vm["name"]))
        if host and host["network"]["name"] != network:
            continue
        chosen.append(vm)
    return ([v for v in chosen if v["type"] != "router"]
            + [v for v in chosen if v["type"] == "router"])


def proxmox_bridge_users(vms, bridge):
    """Names of VMs with a network card on bridge."""
    users = []
    for vm in vms:
        config = vm.get("config") or {}
        for key, value in config.items():
            if re.match(r"^net[0-9]+$", key) and re.search(rf"(^|,)bridge={re.escape(bridge)}(,|$)", str(value)):
                users.append(vm.get("name") or str(vm["vmid"]))
                break
    return users


class FilterModule:
    def filters(self):
        return {
            "network_config_errors": network_config_errors,
            "network_config_proxmox_errors": network_config_proxmox_errors,
            "network_config_summary": network_config_summary,
            "network_config_inventory": network_config_inventory,
            "host_client_networks": host_client_networks,
            "network_cidrs": network_cidrs,
            "placement_candidates": placement_candidates,
            "recorded_address": recorded_address,
            "record_address": record_address,
            "recorded_dns_name": recorded_dns_name,
            "network_config_deploy_order": network_config_deploy_order,
            "nixlab_tags": nixlab_tags,
            "proxmox_tags_merge": proxmox_tags_merge,
            "proxmox_tags_list": _tags,
            "network_config_ownership": network_config_ownership,
            "network_config_destroy_order": network_config_destroy_order,
            "proxmox_bridge_users": proxmox_bridge_users,
        }
