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
HOST_TYPES = ("webserver", "postgres", "gitea", "garage", "router")
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
PORT_FORWARD_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")

NETWORK_KEYS = {"name", "type", "bridge", "cidr", "gateway", "nameserver",
                "upstream", "dhcp", "reserved"}
HOST_KEYS = {"name", "type", "vm_id", "ip", "wan_ip", "full_clone",
             "data_disk", "settings"}


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

        parsed = {"name": name, "type": kind, "bridge": bridge, "cidr": cidr,
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
            self.check_port_forwards(net, where, host.get("settings") or {})
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

    def check_port_forwards(self, net, where, settings):
        forwards = settings.get("port_forwards", []) if isinstance(settings, dict) else []
        if not isinstance(forwards, list):
            self.error(where, "settings.port_forwards must be a list.")
            return
        seen_names, seen_ports = set(), set()
        for fwd in forwards:
            if not isinstance(fwd, dict):
                self.error(where, f"port forward {fwd!r} must be a mapping.")
                continue
            label = f"port forward '{fwd.get('name')}'"
            if not PORT_FORWARD_NAME_RE.match(str(fwd.get("name", ""))):
                self.error(where, f"{label} needs a name of letters, digits, '-' and '_'.")
            proto = fwd.get("proto")
            if proto not in ("tcp", "udp"):
                self.error(where, f"{label}: proto must be tcp or udp.")
            wan_port = _int(fwd.get("wan_port"))
            lan_port = _int(fwd.get("lan_port", fwd.get("wan_port")))
            for key, port in (("wan_port", wan_port), ("lan_port", lan_port)):
                if port is None or not 1 <= port <= 65535:
                    self.error(where, f"{label}: {key} must be from 1 to 65535.")
            if proto == "tcp" and wan_port == 22:
                self.error(where, f"{label}: TCP 22 can't be forwarded; it is the router's own SSH.")
            if fwd.get("name") in seen_names:
                self.error(where, f"{label}: two port forwards have this name.")
            seen_names.add(fwd.get("name"))
            if (proto, wan_port) in seen_ports:
                self.error(where, f"{label}: {proto}/{wan_port} is already forwarded.")
            seen_ports.add((proto, wan_port))
            self.pending_forwards.append((net, where, label, fwd.get("lan_ip")))

    # Driver

    def run(self, network_files):
        self.pending_wan = []
        self.pending_forwards = []
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
        hosts_by_net = {}
        for net, config in parsed:
            hosts_by_net[net["name"]] = self.check_hosts(net, config)
        for net, where, wan_ip in self.pending_wan:
            upstream = self.networks.get(net["upstream"])
            if upstream is not None:
                self.check_address(upstream, where, "wan_ip", wan_ip)
        for net, where, label, lan_ip in self.pending_forwards:
            targets = {str(h.get("ip")) for h in hosts_by_net.get(net["name"], [])
                       if isinstance(h, dict) and h.get("type") != "router"}
            if str(lan_ip) not in targets:
                self.error(where, f"{label}: lan_ip {lan_ip} is not a host on network {net['name']}.")
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


class FilterModule:
    def filters(self):
        return {
            "network_config_errors": network_config_errors,
            "network_config_proxmox_errors": network_config_proxmox_errors,
            "network_config_summary": network_config_summary,
        }
