# Progress bookmark

Progress against [PLAN.md](PLAN.md). The newest entry is at the top.

## Paused before Phase 4

Paused on purpose so Phase 3 can be tried on the live VMs. Phase 4 builds `deploy-network.yaml` on the same per-host play, so problems are easier to find first. Suggested order, with `proxmox/.env` sourced:

```bash
ansible-playbook playbooks/validate-network.yaml
ansible-playbook playbooks/deploy-host.yaml -e network=lab  -e host=router
ansible-playbook playbooks/deploy-host.yaml -e network=lab  -e host=postgres
ansible-playbook playbooks/deploy-host.yaml -e network=home -e host=webserver
ansible-playbook playbooks/deploy-host.yaml -e network=home -e host=gitea
ansible-playbook playbooks/postgres-users.yaml -e network=lab -e host=postgres
```

All the old VMs were destroyed before the refactor started, so every deploy above is a new clone. Expect each one to:

1. Clone the template and add its data disk. The router also gets its `net1`.
2. Boot on the template IP (`192.168.1.10`).
3. Switch to its own address.
4. Get a `nixlab-address: ... on vmbrN` line in its Proxmox notes.

Order matters. The router must come first, since postgres is behind it, and `vmbr1` must still exist. If it doesn't, run `proxmox/scripts/isolated-bridge.yaml`. Postgres must be up before `postgres-users.yaml`. Garage also needs `secrets/home/garage.env`, made from `roles/garage/env.example`.

The Phase 1 live checks further down no longer apply: there were no existing VMs to check against.

### Fix after the first live router run (2026-10-29)

The router deploy failed with "Port forward 'postgres' points at 10.1.0.12, which is not a VM on the isolated LAN". Two causes:

1. **The port forward check ran too early.** The router was found at the template IP (`192.168.1.10`), so its `ens19` had no LAN address yet, and the route check runs before the switch. The old `router.yaml` checked in the same place and would have failed on a new router too.
   - Fix: the route check now runs after the switch.
   - Validation already checks before deploying that each `lan_ip` is a host on the network.
2. **The MAC check ran too late.** It was in `nixos_base`, which the router role only includes after its own checks.
   - Fix: it's now in `roles/nixos_base/tasks/identity.yml`, which `host_deploy` runs right after placement, before any host-type task.

## Phase 3: host types as roles, deployed from the network files (done 2026-10-28, not yet tested live)

**Deploying**
- `playbooks/deploy-host.yaml -e network=<net> -e host=<name>` replaces `hosts/<type>/<type>.yaml`.
- The first play loads and checks the network files, then adds the host and every router to the inventory (`network_config` role, `tasks/inventory.yml`).
- The second play runs over those hosts with `serial: 1`, using [roles/host_deploy](roles/host_deploy/tasks/main.yml). That role runs `<type>/prepare` on the workstation, then `proxmox_vm` and placement there too, then `<type>/configure` on the VM, then `<type>/verify` on the workstation. Phase 4 can use the same play for a whole network.
- `playbooks/destroy-host.yaml` replaces the five `destroy.yaml` files. It refuses to delete a router while VMs of its network still exist.
- `playbooks/postgres-users.yaml` replaces `hosts/postgres/users/users.yaml`. The user list is now under postgres's `settings` in `networks/lab.yaml`, and the reference notes on access levels and roles are in [roles/postgres/USERS.md](roles/postgres/USERS.md).

**Host type roles:** `roles/webserver`, `postgres`, `gitea`, `garage` and `router`.
- Each has `defaults/main.yml`, `prepare.yml`, `configure.yml` and `verify.yml`, and keeps its NixOS files in `files/` and `templates/`, moved with `git mv`.
- Defaults map the host's `settings:` onto the old variable names, so the templates and service tasks are unchanged.
- Rendering each role's templates with today's settings gives the same values as before.
- The router's LAN bridge variable is now `router_lan_bridge`, because `proxmox/vars.yaml` already sets `isolated_bridge` and play vars override role defaults.

**Placement (decision 10)**
- The `network_config_inventory` and `placement_candidates` filters, in [plugins/filter/network_config.py](plugins/filter/network_config.py), work out each VM's attachment (a router attaches upstream at its `wan_ip`) and where to look for it, in this order:
  1. The address recorded in its Proxmox notes.
  2. Its declared address.
  3. The template address.
  4. The far side of an interrupted move.
- `switch.yml` writes `nixlab-address: <ip> on <bridge>` into the VM's Proxmox notes through the API, keeping any other lines.
- `nixos_base` stops if the guest's `ens18` MAC doesn't match `net0`.
- Routers behind which nothing answers are skipped, and a clear error says to deploy the router first.

**Secrets:** `secrets/<network>/<host>.env`, gitignored except [secrets/README.md](secrets/README.md).
- I moved your files without reading them: `hosts/gitea/.env` to `secrets/home/gitea.env`, `hosts/postgres/.env` to `secrets/lab/postgres.env`, and `hosts/postgres/users/.env` to `secrets/lab/postgres-users.env`.
- `gitea.env` was readable by everyone, so I set it to owner-only (600).
- The examples are now `roles/<type>/env.example`.

**Removed**
- All of `hosts/`.
- `hosts/move-network.yaml`. Moving a host is now: move its entry to another network file and deploy it.
- `hosts/router/port-forwards.yaml`. Its tests now run in the router's `verify.yml`.
- The transition test `tests/test_networks_match_host_vars.py`.
- The broken `webserver` entry in `flake.nix`.

**Docs**
- [README.md](README.md): the deploy, addressing and moving sections were rewritten.
- Each `roles/<type>/README.md`: commands and paths updated, plus a table at the top mapping old setting names to network file settings.
- Follow-up: the prose of the role READMEs still uses the old setting names in places. The table covers it, but a rewrite would read better.

**Kept as is on purpose:** the marker `managed by hosts/postgres/users (group)` in `users.sql.j2`. Databases set up earlier carry it, and the users playbook relies on it to recognise its groups.

**Checked**
- 51 unit tests pass.
- Every playbook passes `--syntax-check`.
- Sandbox runs in my scratchpad, against fake Proxmox modules and documentation-only addresses:
  - Deploying gitea, an existing VM, got as far as the SSH lookup. Its secrets were read and its 40 GB disk was left alone.
  - Deploying postgres as a new clone cloned it and added a 20 GB disk, then stopped because the router wasn't answering.
  - Deploying the router added `net1` on `vmbr1`, then looked for the VM at its WAN address and at the template address.
  - `destroy-host` refused a wrong confirmation and refused to delete the router while postgres exists. It deleted postgres once the name was confirmed.
- Not checked: the configure and verify steps, which need real VMs.
- A side effect: the sandbox's postgres runs removed the `10.1.0.12` entry from `~/.ssh/known_hosts`. This is harmless, since the next SSH connection accepts the key again.

## Phase 3 decision (2026-10-28)

Each deploy records the VM's current address in Proxmox. Placement finds the VM there, and its bridge says which network to reach it through. Placement also checks that the guest's `ens18` MAC matches `net0` before changing anything, because every clone shares the template's SSH host key. This is recorded in ARCHITECTURE.MD decision 10 and PLAN.md Phase 3. The QEMU guest agent could replace the recorded address later.

## Before Phase 3: live checks

1. Run the Phase 1 checks listed below (each host playbook on its existing VM).
2. Run `ansible-playbook playbooks/validate-network.yaml` with `proxmox/.env` sourced. This is the first check of the network files against the real Proxmox.

## Phase 2: network files and validation (done 2026-10-28)

- [networks/home.yaml](networks/home.yaml) and [networks/lab.yaml](networks/lab.yaml) describe today's five VMs: same IDs, IPs, disks and settings. lab.yaml includes the router's DHCP, DNS, blocked ranges and port forward.
- [networks/README.md](networks/README.md) documents the schema and what validation checks.
- [plugins/filter/network_config.py](plugins/filter/network_config.py) has the checks:
  - In the files: all settings; uniqueness of names, VM IDs, addresses (including the router's WAN IP) and bridges across all networks; overlapping subnets; addresses inside their subnet and not the network or broadcast address; addresses off the gateway, the template IP, reserved addresses and DHCP ranges; one router per isolated network and none on home networks; upstream networks; port forwards, whose targets must be declared hosts.
  - Against Proxmox: the template exists; no declared ID belongs to a VM with a different name; no declared name exists under a different ID; home bridges exist; existing isolated bridges have no ports and no address.

  It's written in Python with the standard `ipaddress` module, so it can be unit-tested, and it reports every problem at once.
- The [network_config](roles/network_config/) role loads `networks/*.yaml`, runs the checks, and sets `network_configs`, plus `network_config` when `-e network_config_name=<name>` is given. Phase 3 and later use this role.
- [playbooks/validate-network.yaml](playbooks/validate-network.yaml) runs the checks and changes nothing. `-e network_config_check_proxmox=false` skips the Proxmox checks.
- `ansible.cfg` now sets `filter_plugins = plugins/filter`.
- Tests: `.venv/bin/python -m unittest discover -s tests`, 39 tests, all passing:
  - `test_network_config.py`: the real files pass, and each rule catches a broken copy.
  - `test_networks_match_host_vars.py`: the network files agree with `hosts/*/vars.yaml` and `proxmox/vars.yaml`. This keeps them in step until Phase 3 retires the old vars files.
- Checked: the offline validation passes on the real files, and a broken copy reports every problem together.

## Phase 1: shared roles, no behavior change (done 2026-10-28, not yet tested live)

New roles in [roles/](roles/):

- [proxmox_vm](roles/proxmox_vm/tasks/main.yml) handles:
  - the environment variable checks
  - VM lookup and the check that its name matches its ID
  - cloning from the template
  - the optional `scsi1` data disk: add, grow, refuse to shrink
  - extra network cards
  - starting the VM

  It sets `proxmox_vm_existing` and `proxmox_vm_new_clone`.
- [proxmox_vm_remove](roles/proxmox_vm_remove/tasks/main.yml) does the guarded delete:
  - checks the typed confirmation
  - checks the VM name matches its ID
  - stops the VM, then deletes it and its disks
  - forgets its SSH host keys
- [nixos_base](roles/nixos_base/):
  - `main.yml` installs `common.nix` and `network.nix`, and formats a data disk if there is one.
  - `placement.yml`, `placement-try.yml` and `switch.yml` were moved here unchanged from `modules/ansible/`, using `git mv` so their history is kept.
- [dotenv](roles/dotenv/tasks/main.yml) reads a `.env` file into `dotenv_values`. It uses the same parsing and quote stripping as before; I tested this with quoted values, `export`, and a missing file.

Playbooks moved onto the roles:

- `webserver.yaml`, `postgres.yaml`, `gitea.yaml` and `garage.yaml` now use `proxmox_vm`, `nixos_base` and `dotenv`. Each host's own checks and service setup are unchanged.
- `router.yaml` now uses `proxmox_vm`, with `net1` passed as an extra card that is still added before the VM starts, and the shared `switch.yml`. To make that work, the router's inventory entry now carries the same `connect`/`final` vars as the other hosts. This removes the router's separate copy of the build/switch/reconnect steps.
- All five `destroy.yaml` files are now a confirmation prompt plus `proxmox_vm_remove`. Prompts and warnings are unchanged.
- `move-network.yaml` and `postgres/users/users.yaml` use the new role paths and `dotenv`.
- `modules/ansible/` is gone. `modules/common.nix` and `modules/network.nix.j2` stay where they were.

Other fixes:

- `ansible.cfg` no longer sets `inventory = localhost,`. Ansible read it as a path list and tried to parse every file in the repo root as an inventory, which made each run take about 23 seconds.

Small differences in order. None of them change the result:

- The environment variable check now runs after the `.env` checks instead of before them.
- In the configure plays, the data disk is formatted after login, as part of `nixos_base`. Before, it was a separate step at the same point.
- The router now forgets its old host key only for new clones, and `switch.yml` also forgets it when the address changes.

Checked:

- `ansible-playbook --syntax-check` passes for every playbook.

Still to do. You need to run these, since I don't touch the live Proxmox:

```bash
source proxmox/.env
ansible-playbook hosts/router/router.yaml
ansible-playbook hosts/webserver/webserver.yaml
ansible-playbook hosts/postgres/postgres.yaml
ansible-playbook hosts/gitea/gitea.yaml
ansible-playbook hosts/garage/garage.yaml
```

On existing VMs, each run should finish with only the usual changes, such as rewritten config files and a `nixos-rebuild switch` that has nothing to do. Nothing should be cloned, no disks added, and no IPs changed.

## Phase 0: decisions and doc (done 2026-10-28)

- [ARCHITECTURE.MD](ARCHITECTURE.MD):
  - Section 11 now lists the approved decisions instead of open questions.
  - Section 6.1 describes host types as roles, and says why.
  - Section 6.4 shows the target layout.
  - Garage replaces MinIO, and PostgreSQL and the web server are listed as services.
- New [ansible.cfg](ansible.cfg): sets `roles_path = roles`, uses only localhost as inventory, and turns off the "no inventory" warnings. Playbooks must be run from the repository root.
- [README.md](README.md): setup now installs `netaddr` and `ansible.utils`, which Phase 2 needs for IP checks. The layout table lists `ansible.cfg` and `roles/`.
- Installed `netaddr` into `.venv`.
