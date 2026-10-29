# Implementation plan: network-driven deployments

This plan maps the current repository to [ARCHITECTURE.MD](ARCHITECTURE.MD) and sets out how to get from one to the other in small, testable steps. The decisions in section 3 need approval before work starts.

## 1. What already exists

The repo covers more of the architecture than it might seem. The main gap is that every setting is per host. There is no network-level config or orchestrator yet.

| Architecture concept | Current implementation | Gap |
|---|---|---|
| Template | [bootstrap.sh](bootstrap.sh), [proxmox/scripts/](proxmox/scripts/) | None |
| Host lifecycle playbooks | `hosts/<type>/<type>.yaml` + `destroy.yaml` for webserver, postgres, gitea, garage, router | About 100 lines are copied into every playbook: env checks, VM lookup, name check, clone, data disk add/grow/no-shrink, start, placement. The destroy playbooks are nearly identical too. |
| NixOS configs per type | `hosts/<type>/configuration.nix` + `*.nix.j2`, shared [common.nix](modules/common.nix) and [network.nix.j2](modules/network.nix.j2) | Fine as is |
| Network membership | A `<host>_network: home\|isolated` toggle in each `vars.yaml`, plus [move-network.yaml](hosts/move-network.yaml) | Only one home and one isolated network are possible, and the values are hardcoded in [proxmox/vars.yaml](proxmox/vars.yaml) and [hosts/router/vars.yaml](hosts/router/vars.yaml) |
| Firewall VM | NixOS nftables + NAT + dnsmasq ([router](hosts/router/configuration.nix)), with port forwards | Works for one network only. Port forwards are kept separately instead of being derived from the hosts. |
| Isolated bridge | [isolated-bridge.yaml](proxmox/scripts/isolated-bridge.yaml), which already has good guards | Hardcoded to `vmbr1` |
| Destruction guards | Type the name to confirm, VM name must match its ID | No ownership marking, no orphan detection |
| IP allocation | Static, written into `network.nix`. Each clone boots on the template IP `.10`, then moves. | Clones must be deployed one at a time. Nothing checks that IDs and IPs are unique across hosts. |
| Secrets | `hosts/<type>/.env`, parsed with a regex | Tied to the host type, so two Gitea hosts would share one `.env` |
| DNS, reverse proxy, VPN, LDAP | Not built (dnsmasq only forwards queries) | All new |
| MinIO | Garage exists instead | Update ARCHITECTURE.MD |

ARCHITECTURE.MD doesn't mention postgres or webserver. They fit the model as host types.

## 2. The main technical constraint

Ansible's `import_playbook` can't take a variable name, so a network playbook can't loop over `hosts/gitea/gitea.yaml`, `hosts/garage/garage.yaml` and so on. Today each host playbook is "a play on localhost that creates the VM, then a play on the VM". Orchestration needs a different shape:

- **Every declared host becomes an inventory entry** (added with `add_host` from the network file). Each VM is then a real Ansible host.
- **A single play runs over the network's hosts with `serial: 1`.** Proxmox API calls run on the workstation (`delegate_to: localhost`), which is how [switch.yaml](modules/ansible/switch.yaml) already works. Then the play runs `include_role: "{{ host.type }}"`.
- **Standalone use stays:** `playbooks/deploy-host.yaml -e network=lab -e host=gitea` is the same play limited to one host.
- `serial: 1` also handles the template-IP problem: new clones can't both be on `.10` at the same time.

This means turning each `hosts/<type>/` into a role, with the NixOS files moving into that role's `files/` and `templates/` folders. That replaces "one playbook per host type" from ARCHITECTURE.MD §6.1 with "one role per type plus generic create/remove playbooks". This is the cleaner way to meet §6.1, but ARCHITECTURE.MD should be updated to say so.

## 3. Proposed answers to the open decisions (ARCHITECTURE.MD §11)

| # | Decision | Recommendation |
|---|---|---|
| 1 | Schema | One file per network: `networks/<name>.yaml` with a `network:` block and a `hosts:` list, close to the example in ARCHITECTURE.MD. Each host type's defaults live in its role's `defaults/main.yml`. |
| 2 | Network identity | The bridge, CIDR, gateway and router are written out in each network file. The router VM is a host in the list with `type: router`. Validation rejects two networks that share a bridge or subnet. |
| 3 | IP allocation | Keep static addresses in `network.nix`, which already works. Reserve the template IP in `home.yaml`. |
| 4 | Firewall | Keep the NixOS router and drive its settings from the network file |
| 5 | Lifecycle interface | Roles receive a normalized `host` dict and `network` dict (section 2) |
| 6 | Deletion | **Removing a host from the config never deletes it.** A deploy reports orphaned VMs. Deleting them needs `-e prune=true` and typing the network name. `destroy-network.yaml` is a separate playbook and deletes in reverse order: hosts, then router, then the bridge (optional). |
| 7, 10, 11 | State and ownership | Mark managed VMs with Proxmox tags: `nixlab`, `net-<name>`, `type-<type>`. Nothing without the tags is ever deleted. Existing VMs get the tags in a one-time adopt step, which only proceeds when ID and name match. The project manages isolated bridges and uses `vmbr0` as it is. |
| 8 | Dependencies | The order is implied: bridge, then router, then hosts in list order. Explicit `depends_on` only if it turns out to be needed. Validation checks that each proxy backend and port forward points at a declared host. |
| 9 | DNS and TLS | Internal DNS uses `address=` records in the router's existing dnsmasq. TLS starts as plain HTTP internally, and Caddy's internal CA comes with the reverse proxy. |
| 12 | Secrets | Move the `.env` files to `secrets/<network>/<host>.env` (gitignored). Ansible Vault or sops can come later. |

## 4. Phases

Each phase can be tested on its own. The current five VMs keep their IDs and IPs throughout, so none of them has to be rebuilt.

### Phase 0: Decisions and doc

- Confirm section 3.
- Update ARCHITECTURE.MD: Garage instead of MinIO, add postgres and webserver, the role-based lifecycle.
- Add `ansible.cfg` with `roles_path`.
- Add `ansible.utils` + `netaddr` for IP and CIDR checks.

### Phase 1: Remove the duplication, no behavior change

- `roles/proxmox_vm`: lookup, name/ID check, clone, data disk add/grow/no-shrink, start.
- `roles/nixos_base`: `common.nix`, `network.nix`, and the logic from `placement.yaml` and `switch.yaml`.
- `roles/proxmox_vm_remove`: the shared destroy logic.
- Refactor the five existing playbooks onto these roles.
- **Test:** re-run each one against its live VM and check that nothing changes.

### Phase 2: Network files and validation

- `networks/home.yaml` and `networks/lab.yaml` that describe today's setup exactly.
- `playbooks/validate-network.yaml` checks:
  - unique names, IDs and IPs across all network files
  - IPs inside the CIDR, outside the DHCP pool, and not the gateway or template IP
  - bridges exist
  - no VM ID clashes with an unmanaged Proxmox VM
  - every proxy and forward target exists
- Fails before anything changes.

### Phase 3: Host types become roles

- Move `hosts/<type>/` to `roles/<type>/`, reading from `host.*` instead of `gitea_*` variables.
- Add generic `playbooks/deploy-host.yaml` and `destroy-host.yaml`.
- Move secrets to `secrets/<network>/<host>.env`.
- Retire the per-host `vars.yaml` files and `move-network.yaml`. Moving a VM becomes moving its entry to another network file and re-deploying, which reuses the existing placement logic.
- Record each VM's current address in Proxmox on every deploy. Placement looks for the VM there first, then at its declared address, then at the template address. The VM's bridge tells it which network to reach it through.
- Before configuring a VM, check that the guest's `ens18` MAC matches `net0` in Proxmox. Every clone has the template's SSH host key, so this is what proves it's the right VM.

### Phase 4: Network infrastructure and `deploy-network.yaml`

- Make the bridge playbook a role that takes the bridge name as a parameter.
- Make the router a role whose LAN, DHCP, WAN IP and blocked ranges come from the network file.
- The SSH jump host through the router becomes per network.
- `deploy-network.yaml` runs: validate, bridge and router if isolated, hosts one at a time, report.
- **Test:** deploy `lab.yaml` and confirm nothing changes, then deploy a new throwaway `test` network on `vmbr2` using VM IDs 9xx.

### Phase 5: Ownership and reconciliation

- Tags on create.
- The one-time adopt step for existing VMs.
- Orphan report.
- Guarded prune.
- `destroy-network.yaml`.

### Phase 6: Derived configuration

- Port forwards come from each host's `expose:` entries.
- DNS records come from the host list.
- The postgres allowed networks come from network CIDRs.

### Phase 7: New services, one at a time

1. Reverse proxy: a Caddy host type (`proxy`, chosen over nginx for its internal CA), with routes from each host's `proxy:` entries and internal-only by default.
2. VPN: WireGuard on the router, which replaces the SSH jump for admin access.
3. LDAP: lldap is the simplest on NixOS.

### Phase 8: Deployment checks

The ARCHITECTURE.MD §10 checks as a `verify` step at the end of `deploy-network`:

- gateway and routes
- outbound internet works
- the home LAN is blocked
- DNS answers
- proxy routes reach their backends
- no unexpected services are running

## 5. Risks

- **Moving off the per-host `vars.yaml` files** is the riskiest step. A wrong ID or name in the new network file would make the playbook clone a new VM instead of updating the existing one. Validation should therefore stop whenever a declared name exists in Proxmox under a different ID.
- **Several isolated networks** each need their own router, a WAN IP on the home LAN, and their own port-forward numbers. The `10.0.0.0/8` block already stops lab networks from reaching each other. That needs confirming as the intended behavior.
- **Destroying a router** cuts off every host behind it. `destroy-network.yaml` must delete hosts first, and `destroy-host` should refuse to remove a router that still has hosts behind it.
- **Linked clones** still stop `bootstrap.sh --force` from rebuilding the template. This doesn't change.
- [flake.nix](flake.nix) only lists the webserver, so it's stale. The Phase 3 move is a good time to fix it or drop it.
