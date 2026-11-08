# Plan: host names scoped to their network

Today a host name must be unique across all network files, so `lab` and `workstation-lab` can't both have a `router`. This plan makes host names unique only within their own network. A host is then identified as `<network>.<host>`, for example `lab.router` and `workstation-lab.router`.

Unchanged:

- **`vm_id` stays unique across all networks.** It is the Proxmox VM's identity, and every Proxmox lookup goes through it.
- **IP addresses keep today's checks**: unique across all networks (routers' `wan_ip` included), inside the zone's subnet, outside DHCP, not reserved, not the gateway.
- Bridges, subnets and domains stay unique across networks. Since domains are unique, a DNS name `<host>.<domain>` stays unique even when the short name repeats.

## Progress

**All phases are done (2026-11-08, tested live).** The decisions in section 3 were taken as recommended.

Live (2026-11-08):

- `lab` was deployed and checked alongside `workstation-lab` with the new host IDs, and it works.
- Both networks were deployed with the same host names (`router` and `gitea`), and `verify-network.yaml` passes for each (Phase 4 steps 2 and 3).
- `destroy-host.yaml` deleted the right VM when two networks share a host name (step 4).

Checked without Proxmox:

- 179 of 180 unit tests pass, 10 of them new. The one failure is `Examples` for `networks/examples/test.yaml`, which overlaps `workstation-lab` (same subnets and `vmbr3`). That clash existed before this change and was left as it is.
- `--syntax-check` passes on every playbook.
- An offline run of `network_config` and its inventory tasks for `workstation-lab` added `workstation-lab.ws-router`, `.reverse-proxy`, `.ws-gitea` and `.ws`. Each one went through `workstation-lab.ws-router`, and the routers kept their WAN addresses as `ansible_host`.

Differences from the plan below:

- **`network.router` and `network.proxy` stay short names.** Code inside one network uses them that way (DMZ rules, forward names, DNS records). New `router_id` and `proxy_id` hold the IDs, and `attach.via_router` is the router's ID. The inventory tasks, `placement.yml` and gitea's defaults use the `_id` fields.
- **`postgres-users.yaml`** also adds its host under its ID and runs its second play on `<network>.<host>`.
- **The "router isn't answering" hint** in `placement.yml` prints the router's short name for `-e host=`, not its ID.

## 1. Target

```yaml
# networks/lab.yaml
hosts:
  - name: router        # lab.router
    vm_id: 113
  - name: gitea         # lab.gitea
    vm_id: 114

# networks/workstation-lab.yaml
hosts:
  - name: router        # workstation-lab.router  -- allowed
    vm_id: 223
  - name: gitea         # workstation-lab.gitea   -- allowed
    vm_id: 214          # must still differ from every other network's vm_id
```

Commands keep the same arguments, because they already name the network:

```sh
ansible-playbook playbooks/deploy-host.yaml -e network=workstation-lab -e host=router
```

Validation still fails on:

- Two hosts with the same name in **one** file.
- The same `vm_id` in any two files.
- The same IP address in any two files.

## 2. What assumes a global host name today

| Where | What it does with the name | Change |
|---|---|---|
| [network_config.py](../../../plugins/filter/network_config.py) `_Checker.check_host` (`self.unique(self.names, ...)`) | One set of names for all networks | One set per network. |
| `network_config_inventory` (`hosts[h["name"]] = ...`) | `nixlab.hosts` is keyed by short name, so a repeated name silently overwrites the first one | Key by ID `<network>.<host>`. Each entry keeps `name` (short) and gains `id`. |
| `network_config_inventory`: `networks[n].router`, `networks[n].proxy`, `attach.via_router` | Short names, used as inventory host names and as keys into `nixlab.hosts` | IDs. Inside one network, references stay short (see below). |
| `_dmz_rules`, proxy IP lookup (`h["name"] == net["proxy"]`) | Compare the network's proxy and router with short host names | Compare by ID, or by short name against the short part. |
| `network_config_proxmox_errors` | Error when "a VM with this name already exists as VM N" | Only for a VM tagged `net-<this network>` or not tagged at all. A VM with the same name but tagged for another network is fine. Needs the tags in its `by_id` lookup. |
| `network_config_deploy_order`, `network_verify_proxmox`, `unforwarded_ports` | Return or look up short names | IDs. |
| `network_config_ownership`, `network_config_destroy_order` | Key on `(vm_id, name)` | No change: `vm_id` is already unique. |
| [roles/network_config/tasks/inventory.yml](../../../roles/network_config/tasks/inventory.yml) | `add_host name: <short name>` for routers and deploy hosts | `add_host name: <id>`. Two routers called `router` would otherwise be one inventory host. |
| [roles/nixos_base/tasks/placement.yml](../../../roles/nixos_base/tasks/placement.yml) `place_router_wan` | Router name → WAN IP | Router ID → WAN IP. |
| `delegate_to: "{{ final.via_router or 'localhost' }}"` (every role's `verify.yml`, `switch.yml`) | Delegates to the router's inventory name | No edit: `via_router` becomes an ID and the inventory host has that name. |
| [roles/gitea/defaults/main.yml](../../../roles/gitea/defaults/main.yml) `nixlab.hosts[vm.network.proxy]` | Lookup by short name | Works once `proxy` is an ID. |
| [deploy-host.yaml](../../../playbooks/deploy-host.yaml), [destroy-host.yaml](../../../playbooks/destroy-host.yaml), [postgres-users.yaml](../../../playbooks/postgres-users.yaml) | `nixlab.hosts[host]` | `nixlab.hosts[network ~ '.' ~ host]`. The `network.name == network` checks become redundant. |
| [destroy-network.yaml](../../../playbooks/destroy-network.yaml) `destroy_inventory.hosts[item.name]` | Finds the address whose SSH host key to forget, from the Proxmox VM's name | Look up by `vm_id`. With repeated names, the name could point to another network's host, and the wrong key would be forgotten. The VM to delete is already chosen by ID and tag. |
| [roles/network_verify/tasks/summary.yml](../../../roles/network_verify/tasks/summary.yml), [deploy-network.yaml](../../../playbooks/deploy-network.yaml) report | Loop over `groups['nixlab_deploy']` | No edit: these become IDs. Reports show `lab.router` instead of `router`. |

These already work per network and need no change:

- Secrets in `secrets/<network>/<host>.env`.
- DNS records, proxy routes, `reach:`, port-forward names and `expose:` targets. They only refer to hosts of the same network.
- The NixOS `networking.hostName` and NATS `server_name`. They stay the short name.
- `known_hosts` entries, which are keyed by IP address.

## 3. Decisions needing approval

| # | Decision | Recommended | Alternative |
|---|---|---|---|
| 1 | ID format | `<network>.<host>`, e.g. `lab.router`. Both parts are lowercase letters, digits and `-`, so a `.` can't be ambiguous. | `<network>/<host>` (not valid as an Ansible host name in every place) or `<host>@<network>`. |
| 2 | Proxmox VM name | Keep the short host name. Existing VMs keep their names, so nothing in Proxmox is renamed. Two VMs can both be called `router`; the Proxmox UI tells them apart by VM ID and the `net-<network>` tag. Proxmox allows duplicate names. | `<network>-<host>`, unique in the Proxmox UI. Every existing VM would need renaming, and the name checks in `proxmox_vm` and `network_config_proxmox_errors` would need a migration step. |
| 3 | Name in `-e host=` | Short name with `-e network=`, as today. | Also accept `-e host=lab.router` with no `network`. Easy to add later. |
| 4 | Moving a host to another network | Unchanged: found by `vm_id` and the address in its Proxmox notes. A move may now also keep the name while another network already uses it. | — |

## 4. Phases

Each phase leaves the repo working, and the unit tests pass after each one.

### Phase 1: IDs in the inventory, validation unchanged

- `network_config_inventory` keys `hosts` by ID, adds `id`, and makes `router`, `proxy` and `via_router` IDs.
- Update the filters in section 2 that return or look up names.
- `inventory.yml`, `placement.yml` and the playbooks switch to IDs.
- Names are still globally unique in this phase, so behavior is the same except for the longer names in output.
- Tests: update the inventory, deploy-order, DMZ and verify tests for ID keys.

### Phase 2: Scope the name check

- `_Checker`: names unique per network. The error becomes "host name gitea is already used in network lab".
- `network_config_proxmox_errors`: limit the "same name, other VM ID" error as in section 2.
- Tests:
  - Replace `test_duplicate_name_across_networks` with a test that a repeated name across networks is valid.
  - Add a test that the same name twice in one file is an error.
  - Keep and recheck the tests for `vm_id` across networks and address across networks (`test_duplicate_vm_id_across_networks`, `test_duplicate_address_router_wan`).
  - Add an inventory test with `router` in two isolated networks: two entries, each with its own `via_router`.
  - Add a Proxmox-errors test: a VM `router` tagged `net-lab` gives no error for `workstation-lab.router` with another `vm_id`.

### Phase 3: Docs

- [networks/README.md](../../../networks/README.md): in the `name` row, write "Unique within this network". In "What validation checks", split names from VM IDs, addresses and bridges.
- [roles/README.md](../../../roles/README.md): `final.via_router` is the router's ID.
- [docs/ARCHITECTURE.md](../../ARCHITECTURE.md): record the decisions as a new entry in §11.

### Phase 4: Live check

1. Deploy `lab` unchanged and confirm nothing changes on its VMs. Only the names in output change.
2. Rename `ws-router` to `router` in `workstation-lab.yaml`. Then run `deploy-network.yaml -e network=workstation-lab`. Two VMs named `router` exist, each reached through its own WAN address.
3. Run `verify-network.yaml` for both networks.
4. Run `destroy-host.yaml -e network=workstation-lab -e host=router` against a throwaway network first. Confirm it picks the VM by ID and refuses `lab`'s router.

## 5. Risks

- **Silent overwrite.** If Phase 2 ran without Phase 1, two hosts named `router` would collapse into one `nixlab.hosts` entry. A deploy could then use the wrong network's settings for a VM. The phases must go in order, and the inventory test in Phase 2 guards this.
- **Deleting the wrong VM.** `destroy-host`, `destroy-network` and pruning must choose VMs by `vm_id` and the `net-<network>` tag, never by name alone. `proxmox_vm_remove` already requires both tags.
- **Inventory names with dots** look like DNS names to Ansible. Every added host gets `ansible_host` set before it connects (routers in `inventory.yml`, other hosts in `placement.yml`), so Ansible never resolves `lab.router` itself. Check the routers' `add_host` keeps `ansible_host`.
- No Proxmox VM is renamed, recreated or moved by this change.
