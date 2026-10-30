# Network files

Each `<name>.yaml` here describes one network and the VMs on it. The file's name must match `network.name`.

- [home.yaml](home.yaml): VMs directly on the home LAN.
- [lab.yaml](lab.yaml): an isolated network behind the router VM.
- [examples/](examples/): files that validation and deploys don't read, such as [examples/test.yaml](examples/test.yaml), a throwaway isolated network for trying out changes. Copy one into this folder to use it.

Deploy a whole network with `ansible-playbook playbooks/deploy-network.yaml -e network=<name>`, or one host with `playbooks/deploy-host.yaml -e network=<name> -e host=<host>`.

Check every file before deploying:

```bash
source proxmox/.env
ansible-playbook playbooks/validate-network.yaml

# Without Proxmox access, check only the files:
ansible-playbook playbooks/validate-network.yaml -e network_config_check_proxmox=false
```

## `network:`

| Setting | Required | Meaning |
|---|---|---|
| `name` | yes | Same as the file name. Lowercase letters, digits and `-`. |
| `type` | yes | `home`: VMs on an existing LAN whose router is outside this project. `isolated`: a bridge with no physical port, whose only way out is this network's router host. |
| `bridge` | yes | Proxmox bridge, such as `vmbr1`. Each network has its own. A home bridge must already exist. An isolated bridge is created when its router is deployed, and must have no ports and no address if it already exists. |
| `cidr` | yes | Subnet, such as `10.1.0.0/24`. Subnets of different networks may not overlap. |
| `gateway` | yes | Default gateway for hosts. On an isolated network, the router's LAN address. |
| `nameserver` | yes | DNS server for hosts. |
| `upstream` | isolated only | The home network that the router's WAN side is on. |
| `dhcp` | isolated: yes. home: optional | `start`, `end` and `lease_time` (such as `12h`). On an isolated network the router serves this range. On a home network it records the home router's pool, so that no host is given an address from it. |
| `reserved` | no | Addresses no host may use. The gateway and the template's address (`template_ip` in `proxmox/vars.yaml`) are always reserved. |
| `dmz` | no, isolated only | A second bridge behind the router, for hosts that are published. See [DMZ](#dmz). |
| `domain` | no | DNS domain, unique across networks. Defaults to `<name>.home.arpa`. `home.arpa` is reserved for home networks by [RFC 8375](https://www.rfc-editor.org/rfc/rfc8375), so it never clashes with a public domain. On an isolated network, the router's DNS server answers for each host as `<host>` and `<host>.<domain>`. A home network's DNS is the home router's, so there it is only recorded. |

## `hosts:`

| Setting | Required | Meaning |
|---|---|---|
| `name` | yes | VM name in Proxmox, and the host name. Unique across all networks. |
| `type` | yes | Which kind of VM: `webserver`, `postgres`, `gitea`, `garage`, `router`, `proxy` or `ldap`. |
| `vm_id` | yes | Proxmox VM ID. Unique across all networks, and not the template's. An existing VM with this ID must have this name. |
| `ip` | yes | Fixed address inside `cidr` (or `dmz.cidr` for a DMZ host), outside the DHCP range, and unique across all networks. A router's `ip` is its LAN address and must equal `gateway`. |
| `zone` | no | `lan` (the default) or `dmz`, which puts the host on the network's [DMZ](#dmz) bridge. Not for routers. |
| `reach` | no, DMZ hosts only | LAN hosts this DMZ host may connect to, beyond its proxy's backends. Each entry has `host` (a LAN host on the same network), `port`, and optionally `proto` (`tcp` or `udp`, defaults to `tcp`). |
| `wan_ip` | routers only | The router's address on the upstream network |
| `full_clone` | no | `true` for a full copy of the template instead of a linked clone. Defaults to `false`. |
| `data_disk` | postgres, gitea, garage | `size_gb` and `storage`. It can grow but never shrink. |
| `expose` | no, isolated networks only | Ports forwarded to this host from its router's WAN address. Each entry has `port` (on the host), and optionally `wan_port` (on the router, defaults to `port`), `proto` (`tcp` or `udp`, defaults to `tcp`) and `name` (needed when a host has more than one). Redeploy the router after changing these. |
| `proxy` | no | Web services on this host for the network's `proxy` host to serve over HTTPS. Each entry has `name`, one DNS label, served as `<name>.<domain>`, and `port`, the port on this host. `external: true` also publishes it through the router's TCP 443 and 80 (isolated networks only; off by default). Needs a host of type `proxy` on the same network. See [roles/proxy](../roles/proxy/README.md). |
| `settings` | no | Settings for this host type. The defaults are in the host type's role. |

## DMZ

An isolated network can have a DMZ: a second bridge behind the same router, for hosts reached from outside, such as the proxy. If one is taken over, it still can't reach the rest of the network.

```yaml
network:
  name: lab
  # ...
  dmz:
    bridge: vmbr2            # created by the router's deploy if missing
    cidr: 10.1.1.0/24
    gateway: 10.1.1.1        # the router's DMZ address, also the DMZ's DNS server
    # dhcp:                  # off when unset: DMZ hosts all have fixed addresses
    #   start: 10.1.1.100
    #   end: 10.1.1.199
    #   lease_time: 12h
    # reserved: []

hosts:
  - name: proxy
    type: proxy
    zone: dmz
    vm_id: 116
    ip: 10.1.1.10
    # reach:                 # more LAN access, beyond the proxy's backends
    #   - host: ldap
    #     port: 3890
```

| From → to | LAN | DMZ | Home / private networks | Internet |
|---|---|---|---|---|
| LAN | yes | yes | no | yes |
| DMZ | only DMZ rules | yes | no | yes |
| VPN | yes | yes | no | no |
| Home (WAN) | `expose:` only | `expose:` only | | |

**DMZ rules** are the only way from the DMZ into the LAN, one host and port at a time. They come from two places:

- **Proxy routes.** When the proxy is in the DMZ, it may reach each route's backend on the LAN, on the route's port.
- **`reach:`** on a DMZ host, for anything else.

The router's DNS server answers for every host on both bridges. DMZ hosts can look up LAN names but can't connect to them. The proxy's internal routes don't accept connections from the DMZ either, so a DMZ host can't use the proxy to get around the rules.

Moving a host to the DMZ is a change of `zone` and `ip`. Redeploy the network: the router goes first and gets its DMZ card and rules, then the host moves to the DMZ bridge.

Validation warns, without stopping, about a host that is published but still on the LAN of a network with a DMZ: one with `expose:` entries, or a proxy with external routes.

`expose:` replaces the router's old `settings.port_forwards`. Each router port can be forwarded to only one host, and TCP 22 on the router can't be used: it is the router's own SSH.

Postgres's `settings.allowed_networks` takes network names as well as subnets. Left unset, it is the host's own network, plus the upstream network when the host has `expose:` entries.

## What is derived from the files

| What | From |
|---|---|
| The router's port forwards | `expose:` on the network's hosts |
| The router's DNS records | Every host on the network, under `domain`, plus each proxy route at the proxy's address |
| The proxy's sites | `proxy:` on the network's hosts |
| Postgres password logins | `settings.allowed_networks`, or the networks that can reach the host, including DMZ hosts with a DMZ rule to it |
| The router's DMZ rules | Proxy routes from a DMZ proxy to LAN hosts, and `reach:` entries |

## What validation checks

Checked in the files, by [plugins/filter/network_config.py](../plugins/filter/network_config.py):

- Every setting above, including `expose:`, `proxy:`, `domain`, `dmz`, `zone` and `reach:`.
- A DMZ's bridge and subnet are unique like a network's, and each host's `ip` is in its zone's subnet.
- A network with `proxy:` routes has exactly one `proxy` host, and no route has a host's name.
- Names, VM IDs, addresses (including routers' `wan_ip`) and bridges are unique across all networks.
- Subnets don't overlap.

Checked against Proxmox:

- The template exists.
- No declared VM ID belongs to a VM with another name.
- No declared name already exists under another ID. Otherwise deploying would clone a second copy.
- Home bridges exist, and an existing isolated bridge (including a DMZ bridge) really is isolated.

It also reports, per network, VMs tagged for it that no file lists any more, VMs moved to another file, and VMs not yet tagged. It fails if a removed VM still holds an address a file gives another host. See "Which VMs are the project's" in the main README.

Validation never changes anything.
