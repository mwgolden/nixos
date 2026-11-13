# Host identity and moving hosts

A host's name only has to be unique within its network: `lab` and `home` can both have a `ws`. This page covers how deploys tell those hosts apart, how to move a host to another network, and what happens when the network you move to already has a host with the same name.

## How a host is identified

| What | Unique across | Used for |
|---|---|---|
| `vm_id` | every network | The Proxmox VM. Every Proxmox lookup, and every move, goes through it. |
| Host ID, `<network>.<host>` (such as `lab.ws`) | every network | The Ansible inventory name, and `nixlab.hosts` keys. |
| `name` | its own network | The Proxmox VM name, `networking.hostName`, DNS, secrets files. |

`deploy-host.yaml -e network=lab -e host=ws` picks the `ws` entry in `networks/lab.yaml` and works on that entry's `vm_id`. It never looks at another network's `ws`.

## Same name, different VMs

If two network files each have a `ws` with a **different** `vm_id`, they are two separate hosts:

```yaml
# networks/home.yaml
- name: ws
  vm_id: 119
  ip: 192.168.1.8

# networks/lab.yaml
- name: ws
  vm_id: 120
  ip: 10.1.0.10
```

Deploying `-e network=lab -e host=ws` creates VM 120, or updates it in place if it already exists. VM 119 is not touched. This is not a move.

## Moving a host

A move is defined by `vm_id`, not by name. To move `home.ws` (VM 119) to `lab`:

1. Remove the `ws` entry from `networks/home.yaml`.
2. Add it to `networks/lab.yaml` with the **same** `vm_id: 119` and an address in `lab`.
3. Copy its secrets file, if it has one, from `secrets/home/` to `secrets/lab/` (see [Secrets](#secrets-are-found-by-name)).
4. Run `ansible-playbook playbooks/deploy-host.yaml -e network=lab -e host=ws`.

The deploy finds VM 119 where it was last deployed, from the address recorded in its Proxmox notes. It then moves the VM's network card to the new bridge and the VM to its new address, and updates the VM's `net-<network>` tag. The diagrams of both networks are rewritten.

The host can be renamed in the same move only if you also rename the VM in Proxmox first. Deploys never rename VMs (see case 2 below).

## Moving onto a name that is already taken

Say `lab` already has `ws` (VM 120), and you want to move `home.ws` (VM 119) there.

| You put in `lab.yaml` | Result |
|---|---|
| **1.** Both entries, both called `ws` | Rejected by validation: a name can appear only once in a network file. Nothing runs. |
| **2.** VM 119 under a new name, such as `ws2` | Rejected before any change: "VM 119 exists but is named 'ws'". Rename the VM in Proxmox first (`qm set 119 --name ws2`). |
| **3.** VM 119 as `ws`, replacing VM 120's entry | Rejected while VM 120 exists: "a VM with this name already exists as VM 120". VM 120 is named `ws` and tagged `net-lab`, so deploying would leave two `ws` VMs on `lab`. Delete VM 120 first: prune it, or run `destroy-host.yaml` before you edit the file. |

The check in case 3 only counts VMs tagged for the target network, or with no network tag at all. A `ws` VM tagged for another network is fine. That is what lets `home.ws` and `lab.ws` exist together.

If the checks above were somehow bypassed, two more checks stop a deploy before it changes the wrong VM:

- The VM is found by `vm_id`, at addresses taken from that VM's own Proxmox notes, never by name or DNS.
- After connecting, the deploy compares the VM's MAC address with the MAC in that `vm_id`'s Proxmox config ([identity.yml](../roles/nixos_base/tasks/identity.yml)). If they differ, it stops without changing anything.

## Secrets are found by name

Secrets are read from `secrets/<network>/<host>.env`, keyed by name, not by `vm_id`. There is no check for this.

In case 3, the moved VM 119 would read `secrets/lab/ws.env`, which was written for VM 120, not the file it used on `home`. For roles that create an admin user or set a password from the secrets file, such as gitea, the moved host ends up with the old host's login. Its data is not lost, but the credentials change.

When you move a host, check that `secrets/<new network>/<host>.env` holds the values you want the moved VM to have.
