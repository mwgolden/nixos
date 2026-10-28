# Progress bookmark

Progress against [PLAN.md](PLAN.md). The newest entry is at the top.

## Paused before Phase 3

Work is paused here on purpose, and not because of the token limit. Phase 3 rewrites every host playbook a second time, this time to read the network files. It should build on Phase 1 only after Phase 1 has been run against the live VMs. Before resuming:

1. Run the Phase 1 checks listed below (each host playbook on its existing VM).
2. Run `ansible-playbook playbooks/validate-network.yaml` with `proxmox/.env` sourced. This is the first check of the network files against the real Proxmox.

Decided for Phase 3 (2026-10-28): each deploy records the VM's current address in Proxmox. Placement finds the VM there, and its bridge says which network to reach it through. Placement also checks that the guest's `ens18` MAC matches `net0` before changing anything, because every clone shares the template's SSH host key. This is recorded in ARCHITECTURE.MD decision 10 and in PLAN.md Phase 3. The QEMU guest agent could replace the recorded address later.

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
