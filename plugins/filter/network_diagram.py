"""Diagrams of deployed networks, written to docs/network-diagrams/.

Used from roles/network_config/tasks/diagram.yml. Each network gets a
Markdown file with a Mermaid flowchart and tables of the same data, made
from network_config_inventory. The output depends only on the inventory
and on which hosts exist, so a redeploy with no changes writes the same
text.

    {{ nixlab | network_diagram('lab', deployed) }}
    {{ nixlab | network_diagram_index(['home', 'lab'], deployed) }}

deployed is a list of host IDs (<network>.<host>) whose VMs exist, from
network_diagram_deployed. Hosts not in it are drawn as not deployed.
"""

import re

HEADER = ("Generated from [networks/{name}.yaml](../../networks/{name}.yaml) when the network "
          "is deployed or changed. Don't edit it: redeploy, or run "
          "`playbooks/diagram-network.yaml`, to update it.")


def _label(*lines):
    """A quoted Mermaid label. Lines are joined with <br/>; characters that
    would end the label or start markup are replaced by entities."""
    def esc(text):
        return (str(text).replace("&", "#amp;").replace('"', "#quot;")
                .replace("<", "#lt;").replace(">", "#gt;"))
    return '"' + "<br/>".join(esc(line) for line in lines if line != "") + '"'


def _node(name):
    """A Mermaid node ID for a host name. Host names are lowercase letters,
    digits and '-', so this can't clash; the prefix keeps words like 'end'
    from being read as keywords."""
    return "h_" + name.replace("-", "_")


def _cell(value):
    return str(value).replace("|", "\\|") if value not in (None, "") else "—"


def _table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(_cell(v) for v in row) + " |" for row in rows]
    return lines


def _dhcp(dhcp):
    if not dhcp:
        return "no DHCP"
    start, end = str(dhcp["start"]), str(dhcp["end"])
    return f"DHCP .{start.rsplit('.', 1)[-1]} to .{end.rsplit('.', 1)[-1]}"


def _service_ports(host, net):
    """Ports a host is reached on, as the network file declares them: its
    proxy route backends and expose: entries, and 443/80 on the proxy when
    it has routes."""
    ports = []
    if host["name"] == net["proxy"] and net["proxy_routes"]:
        ports += ["tcp 443", "tcp 80"]
    for r in net["proxy_routes"]:
        if r["host"] == host["name"]:
            ports.append(f"tcp {r['port']}")
    for e in host.get("expose") or []:
        ports.append(f"{e['proto']} {e['port']}")
    return list(dict.fromkeys(ports))


def _hosts(inventory, network):
    """The network's hosts, in file order (the inventory keeps it)."""
    return [h for h in inventory["hosts"].values() if h["network"]["name"] == network]


def network_diagram_deployed(inventory, vms=None):
    """IDs of the hosts whose VMs exist: a VM with the host's ID and name.
    vms: proxmox_vm_info's proxmox_vms. None (Proxmox not read) counts every
    declared host as deployed."""
    if vms is None:
        return sorted(inventory["hosts"])
    existing = {(int(v["vmid"]), v.get("name")) for v in vms}
    return sorted(hid for hid, h in inventory["hosts"].items() if (h["vm_id"], h["name"]) in existing)


def vm_tagged_networks(vms, vm_id):
    """The networks a VM is tagged for (its net-<network> tags), or [] if
    there is no such VM. Used to find the network a moved host left."""
    for vm in vms or []:
        if int(vm["vmid"]) == int(vm_id):
            config = vm.get("config") or {}
            tags = [t for t in re.split(r"[;, ]+", config.get("tags") or vm.get("tags") or "") if t]
            return [t[len("net-"):] for t in tags if t.startswith("net-")]
    return []


def _host_node(h, net, deployed, indent):
    lines = [f"{h['name']}, VM {h['vm_id']}", f"{h['type']}, {h['ip']}"]
    ports = _service_ports(h, net)
    if ports:
        lines.append(", ".join(ports))
    if h["id"] not in deployed:
        lines.append("not deployed")
    return f"{indent}{_node(h['name'])}[{_label(*lines)}]"


def _flowchart(inventory, network, deployed):
    net = inventory["networks"][network]
    hosts = _hosts(inventory, network)
    deployed = set(deployed)
    out = ["```mermaid", "flowchart TB"]
    pending = [h for h in hosts if h["id"] not in deployed]

    if net["type"] == "home":
        out.append(f"    subgraph net[{_label(f'{network} {net['cidr']} on {net['bridge']}', _dhcp_home(net))}]")
        out.append(f"        gw[{_label('home gateway and DNS', net['gateway'])}]")
        for h in hosts:
            out.append(_host_node(h, net, deployed, "        "))
        routers = [n for n in inventory["networks"].values()
                   if n["type"] == "isolated" and n["upstream"] == network and n["router"]]
        for other in routers:
            router = inventory["hosts"][other["router_id"]]
            out.append(f"        r_{other['name'].replace('-', '_')}"
                       f"[{_label(f'router of {other['name']}, VM {router['vm_id']}', f'WAN {other['router_wan_ip']}', '' if router['id'] in deployed else 'not deployed')}]")
        out.append("    end")
        for h in hosts:
            out.append(f"    gw <--> {_node(h['name'])}")
        for other in routers:
            out.append(f"    gw <--> r_{other['name'].replace('-', '_')}")
    else:
        up = inventory["networks"].get(net["upstream"]) or {}
        out.append(f"    up[{_label(f'{up.get('name', net['upstream'])} {up.get('cidr', '')} on {up.get('bridge', '')}', f'gateway {up.get('gateway', '')}')}]")
        router = inventory["hosts"].get(net["router_id"]) if net["router_id"] else None
        if router:
            lines = [f"{router['name']}, VM {router['vm_id']}", f"WAN {net['router_wan_ip']}", f"LAN {net['gateway']}"]
            if net["dmz"]:
                lines.append(f"DMZ {net['dmz']['gateway']}")
            lines.append("NAT, firewall, DHCP, DNS")
            if router["id"] not in deployed:
                lines.append("not deployed")
            out.append(f"    {_node(router['name'])}[{_label(*lines)}]")
        lan = [h for h in hosts if h["type"] != "router" and h["zone"] == "lan"]
        dmz = [h for h in hosts if h["zone"] == "dmz"]
        out.append(f"    subgraph lan[{_label(f'LAN {net['cidr']} on {net['bridge']}', _dhcp(net['dhcp']))}]")
        for h in lan:
            out.append(_host_node(h, net, deployed, "        "))
        if not lan:
            out.append(f"        lan_empty[{_label('no hosts')}]")
        out.append("    end")
        if net["dmz"]:
            out.append(f"    subgraph dmz[{_label(f'DMZ {net['dmz']['cidr']} on {net['dmz']['bridge']}', _dhcp(net['dmz']['dhcp']))}]")
            for h in dmz:
                out.append(_host_node(h, net, deployed, "        "))
            if not dmz:
                out.append(f"        dmz_empty[{_label('no hosts')}]")
            out.append("    end")
        if net["vpn"]:
            vpn = net["vpn"]
            peers = ", ".join(p["name"] for p in vpn["peers"])
            out.append(f"    vpn(({_label('VPN clients', vpn['cidr'], peers)}))")

        if router:
            r = _node(router["name"])
            out.append(f"    up <-->|{_label('ens18 WAN ' + net['router_wan_ip'])}| {r}")
            out.append(f"    {r} <-->|{_label('ens19 LAN ' + net['gateway'])}| lan")
            if net["dmz"]:
                out.append(f"    {r} <-->|{_label('ens20 DMZ ' + net['dmz']['gateway'])}| dmz")
        wan = net["router_wan_ip"]
        external = [r for r in net["proxy_routes"] if r["external"]]
        if external and net["proxy"]:
            names = ", ".join(r["fqdn"] for r in external)
            out.append(f"    up -.->|{_label(f'external routes {wan}:443', names)}| {_node(net['proxy'])}")
        proxy_forwards = {f"{net['proxy']}-https", f"{net['proxy']}-http"} if net["proxy"] else set()
        for f in net["port_forwards"]:
            if f["name"] in proxy_forwards:
                continue
            out.append(f"    up -.->|{_label(f'port forward {f['proto']} {wan}:{f['wan_port']}')}| {_node(f['host'])}")
        if net["proxy"]:
            for r in net["proxy_routes"]:
                kind = "external" if r["external"] else "internal"
                out.append(f"    {_node(net['proxy'])} -.->|{_label(f'route {r['name']} ({kind}), tcp {r['port']}')}| {_node(r['host'])}")
        routed = {(net["proxy"], r["host"], "tcp", r["port"]) for r in net["proxy_routes"]}
        for rule in net["dmz_rules"]:
            if (rule["src_host"], rule["dst_host"], rule["proto"], rule["port"]) in routed:
                continue
            out.append(f"    {_node(rule['src_host'])} -.->|{_label(f'reach {rule['proto']} {rule['port']}')}| {_node(rule['dst_host'])}")
        if net["vpn"]:
            out.append(f"    vpn -.->|{_label(f'udp {net['vpn']['endpoint']}')}| {_node(net['router']) if router else 'lan'}")
        out.append(f"    lan -.->|{_label('outbound, NAT through ' + wan)}| up")
        blocked = (router or {}).get("settings", {}).get("blocked_networks") or []
        if blocked:
            out.append(f"    lan -.-x|{_label('blocked: ' + ', '.join(str(b) for b in blocked))}| up")

    if net["type"] == "home":
        pending_ids = [_node(h["name"]) for h in pending] + [
            "r_" + n["name"].replace("-", "_") for n in inventory["networks"].values()
            if n["type"] == "isolated" and n["upstream"] == network and n["router"]
            and n["router_id"] not in deployed]
    else:
        pending_ids = [_node(h["name"]) for h in pending]
    if pending_ids:
        out.append("    classDef pending stroke-dasharray: 5 5")
        out.append("    class " + ",".join(pending_ids) + " pending")
    out.append("```")
    return out


def _dhcp_home(net):
    return f"gateway {net['gateway']}, DHCP by the home router"


def network_diagram(inventory, network, deployed):
    """The Markdown for docs/network-diagrams/<network>.md."""
    net = inventory["networks"][network]
    hosts = _hosts(inventory, network)
    deployed = set(deployed)
    out = [f"# Network {network}", "", HEADER.format(name=network), ""]
    summary = f"{net['type'].capitalize()} network {net['cidr']} on {net['bridge']}"
    if net["type"] == "isolated":
        summary += f", behind {net['router'] or 'no router'} on {net['upstream']} at {net['router_wan_ip']}"
        summary += f". DNS domain {net['domain']}"
    count = sum(1 for h in hosts if h["id"] in deployed)
    out += [summary + f". {count} of {len(hosts)} host{'' if len(hosts) == 1 else 's'} deployed.", ""]
    out += _flowchart(inventory, network, deployed)

    out += ["", "## Hosts", ""]
    out += _table(["Host", "Type", "VM ID", "Zone", "Address", "Ports", "Data disk", "Deployed"],
                  [[h["name"], h["type"], h["vm_id"], "router" if h["type"] == "router" else h["zone"],
                    h["attach"]["ip"] + (f" (LAN {h['ip']})" if h["type"] == "router" else ""),
                    ", ".join(_service_ports(h, net)),
                    f"{h['data_disk']['size_gb']} GB on {h['data_disk']['storage']}" if h["data_disk"] else "",
                    "yes" if h["id"] in deployed else "no"] for h in hosts])

    if net["port_forwards"]:
        out += ["", "## Port forwards", "", f"From the router's WAN address, {net['router_wan_ip']}.", ""]
        out += _table(["Name", "Protocol", "WAN port", "To"],
                      [[f["name"], f["proto"], f["wan_port"], f"{f['host']} {f['lan_ip']}:{f['lan_port']}"]
                       for f in net["port_forwards"]])
    if net["proxy_routes"]:
        out += ["", "## Proxy routes", "", f"Served by {net['proxy']}.", ""]
        out += _table(["Route", "Name", "Backend", "External"],
                      [[r["name"], r["fqdn"], f"{r['host']} {r['backend_ip']}:{r['port']}",
                        "yes" if r["external"] else "no"] for r in net["proxy_routes"]])
    if net["dmz_rules"]:
        out += ["", "## DMZ to LAN rules", ""]
        out += _table(["From", "To", "Port"],
                      [[f"{r['src_host']} {r['src_ip']}", f"{r['dst_host']} {r['dst_ip']}",
                        f"{r['proto']} {r['port']}"] for r in net["dmz_rules"]])
    if net["vpn"]:
        vpn = net["vpn"]
        out += ["", "## VPN", "",
                f"WireGuard on the router at {vpn['endpoint']}, subnet {vpn['cidr']}. "
                f"Clients route {', '.join(vpn['allowed_ips'])}.", ""]
        out += _table(["Peer", "Address"], [[p["name"], p["ip"]] for p in vpn["peers"]])
    return "\n".join(out) + "\n"


def networks_with_deployed_hosts(inventory, networks, deployed):
    """The networks, in order, that have at least one deployed host."""
    deployed = set(deployed)
    return [n for n in networks if any(h["id"] in deployed for h in _hosts(inventory, n))]


def network_diagram_targets(inventory, networks):
    """networks plus the upstream network of each isolated one: a home
    network's diagram shows the routers on it."""
    result = []
    for name in networks:
        net = inventory["networks"].get(name)
        if net is None:
            continue
        for n in (name, net["upstream"] if net["type"] == "isolated" else ""):
            if n and n in inventory["networks"] and n not in result:
                result.append(n)
    return result


def network_diagram_index(inventory, networks, deployed):
    """The Markdown for docs/network-diagrams/README.md: a table of the
    networks that have diagrams, and how they connect."""
    deployed = set(deployed)
    nets = [inventory["networks"][n] for n in sorted(networks) if n in inventory["networks"]]
    out = ["# Network diagrams", "",
           "One file per network, written when the network is deployed or changed. "
           "Don't edit them: redeploy, or run `playbooks/diagram-network.yaml`, to update them.", ""]
    rows = []
    for n in nets:
        hosts = _hosts(inventory, n["name"])
        rows.append([f"[{n['name']}]({n['name']}.md)", n["type"], n["cidr"], n["bridge"],
                     n["router_wan_ip"] if n["type"] == "isolated" else "",
                     f"{sum(1 for h in hosts if h['id'] in deployed)} of {len(hosts)}"])
    out += _table(["Network", "Type", "Subnet", "Bridge", "Router WAN", "Hosts deployed"], rows)
    out += ["", "```mermaid", "flowchart TB"]
    for n in nets:
        node = "n_" + n["name"].replace("-", "_")
        lines = [n["name"], f"{n['cidr']} on {n['bridge']}"]
        if n.get("dmz"):
            lines.append(f"DMZ {n['dmz']['cidr']} on {n['dmz']['bridge']}")
        count = len(_hosts(inventory, n["name"]))
        lines.append(f"{count} host" + ("" if count == 1 else "s"))
        out.append(f"    {node}[{_label(*lines)}]")
    for n in nets:
        if n["type"] == "isolated" and n["upstream"] in networks:
            out.append(f"    n_{n['upstream'].replace('-', '_')} <-->|"
                       f"{_label(f'{n['router']} WAN {n['router_wan_ip']}')}| n_{n['name'].replace('-', '_')}")
    out.append("```")
    return "\n".join(out) + "\n"


class FilterModule:
    def filters(self):
        return {
            "network_diagram": network_diagram,
            "network_diagram_index": network_diagram_index,
            "network_diagram_deployed": network_diagram_deployed,
            "network_diagram_targets": network_diagram_targets,
            "networks_with_deployed_hosts": networks_with_deployed_hosts,
            "vm_tagged_networks": vm_tagged_networks,
        }
