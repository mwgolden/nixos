# Network checks

Checks a deployed network end to end. It runs at the end of `deploy-network.yaml`, once every host is deployed, and on its own with:

```bash
source proxmox/.env
ansible-playbook playbooks/verify-network.yaml -e network=lab
```

Nothing is changed. Every check runs, then one report lists each host as `ok` or with its problems. The run fails if there are any. The VMs stay as deployed, so fix the problem and run `verify-network.yaml` again.

## What is checked

On each VM, over SSH (through the router on an isolated network):

| Check | Passes when |
|---|---|
| SSH | The VM answers at its address from the network file |
| Address | `ens18` has the host's address and prefix |
| Gateway | The default route goes through the network's gateway on `ens18` |
| Network DNS | On an isolated network, every host's and proxy route's name resolves to the right address |
| Public DNS and internet | `cache.nixos.org` resolves and answers on TCP 443 |
| Isolation | On an isolated network, the VM can't reach the home gateway, the Proxmox web interface or any other network's gateway. A dropped connection (timeout) passes; an answer or a refusal means the packet got through. |
| DMZ | On a network with a DMZ: from the DMZ, SSH on each LAN host is dropped (unless a DMZ rule allows it), and each DMZ rule's port answers or refuses. From the LAN, SSH on each DMZ host answers. |
| Listening services | Nothing listens on a non-loopback TCP port except 22 and the host type's own ports, from `roles/<type>/tasks/ports.yml` |
| Proxy routes | On a proxy, each route answers over HTTPS. A 502 or 504 means its backend isn't answering. |

From this machine:

| Check | Passes when |
|---|---|
| Proxmox | Each VM exists, is running, and has `net0` (and a router's `net1`, and `net2` with a DMZ) on the right bridge |
| Router ports | On an isolated network, the router's WAN address doesn't answer on any port that the network's hosts listen on but that no `expose:` entry or external route forwards |
| Routes from home | When a network has external routes: external ones answer through the router's 443, and internal ones refuse |

UDP isn't checked.

## Settings

In [defaults/main.yml](defaults/main.yml), which you can override with `-e`:

| Setting | Default | Meaning |
|---|---|---|
| `network_verify_internet_host` | `cache.nixos.org` | The public name every VM must resolve and reach |
| `network_verify_internet_port` | `443` | Its TCP port |
| `network_verify_timeout` | `4` | Seconds per connection attempt. Blocked attempts take this long. |

## Files

- [tasks/main.yml](tasks/main.yml): the checks on one VM. They're noted in `verify_problems`, and nothing stops on the first failure.
- [tasks/summary.yml](tasks/summary.yml): the checks from this machine, and the report.
- [files/probe.py](files/probe.py): TCP and HTTPS probes using only Python's standard library, run on the VMs and here.
- The filters `unexpected_listeners`, `blocked_targets`, `reachable_targets`, `network_verify_proxmox`, `unforwarded_ports` and `nixlab_ssh_args` in [plugins/filter/network_config.py](../../plugins/filter/network_config.py), tested in `tests/test_verify.py` and `tests/test_dmz.py`.

A new host type needs a `tasks/ports.yml` that sets `verify_expected_ports`.
