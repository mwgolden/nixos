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

## `hosts:`

| Setting | Required | Meaning |
|---|---|---|
| `name` | yes | VM name in Proxmox, and the host name. Unique across all networks. |
| `type` | yes | Which kind of VM: `webserver`, `postgres`, `gitea`, `garage` or `router`. |
| `vm_id` | yes | Proxmox VM ID. Unique across all networks, and not the template's. An existing VM with this ID must have this name. |
| `ip` | yes | Fixed address inside `cidr`, outside the DHCP range, and unique across all networks. A router's `ip` is its LAN address and must equal `gateway`. |
| `wan_ip` | routers only | The router's address on the upstream network |
| `full_clone` | no | `true` for a full copy of the template instead of a linked clone. Defaults to `false`. |
| `data_disk` | postgres, gitea, garage | `size_gb` and `storage`. It can grow but never shrink. |
| `settings` | no | Settings for this host type. The defaults are in the host type's role. |

A router's `settings.port_forwards` entries need `name`, `proto` (`tcp` or `udp`), `wan_port`, `lan_ip` and optionally `lan_port`. `lan_ip` must be another host on the same network, and TCP 22 can't be forwarded.

## What validation checks

Checked in the files, by [plugins/filter/network_config.py](../plugins/filter/network_config.py):

- Every setting above.
- Names, VM IDs, addresses (including routers' `wan_ip`) and bridges are unique across all networks.
- Subnets don't overlap.

Checked against Proxmox:

- The template exists.
- No declared VM ID belongs to a VM with another name.
- No declared name already exists under another ID. Otherwise deploying would clone a second copy.
- Home bridges exist, and an existing isolated bridge really is isolated.

It also reports, per network, VMs tagged for it that no file lists any more, VMs moved to another file, and VMs not yet tagged. It fails if a removed VM still holds an address a file gives another host. See "Which VMs are the project's" in the main README.

Validation never changes anything.
