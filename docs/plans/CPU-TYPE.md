# Plan: set each VM's CPU type

No part of this project sets a VM's CPU type, so every VM gets Proxmox's old default, `kvm64`. That model hides most instructions newer than about 2004 from the guest, SSE4.2 among them. Programs built for newer CPUs then fail at start. The first one found was Claude Code on a workstation:

```text
error: this CPU is missing SSE4.2 support, which Bun requires.
  If this is a VM, enable host CPU passthrough (e.g. -cpu host for QEMU/KVM).
```

Python wheels, Node.js add-ons, databases and compilers increasingly expect at least x86-64-v2. Some run noticeably slower without AVX2 (x86-64-v3).

This plan sets a CPU type on every VM: a project default, with a per-host override in the network files. Deploys apply it to new and existing VMs.

## Progress

**Phases 1–3 are done (2026-11-13). Phase 4, the live check, isn't.** The decisions in section 3 were taken as recommended.

Checked without Proxmox:

- 14 new unit tests in [tests/test_cpu_type.py](../../tests/test_cpu_type.py) pass: allowed and rejected `cpu:` values, `vm_cpu_type`, the inventory, and reading `/pending` responses. The full suite has the one failure it had before (`Examples`).
- `--syntax-check` passes on every playbook and on `create-template.yaml`.
- The end-of-run list in `deploy-network.yaml` and the "permission refused" message were rendered with fake data.

Differences from the plan below:

- **The inventory keeps a host's own `cpu:`**, or `""` when it isn't set. [host_deploy](../../roles/host_deploy/tasks/main.yml) fills in `vm_cpu_type` when it calls `proxmox_vm`. Otherwise all seven places that build the inventory would need `vm_cpu_type` passed in. `vm_cpu_type` is still checked with the network files.
- **The pending state is read before the change too.** A change already waiting isn't sent again on every deploy, and one made by hand in Proxmox is reported. The filter is `proxmox_cpu_state`, which returns `{current, next, pending}`.
- **The CPU change has its own request** in [cpu.yml](../../roles/proxmox_vm/tasks/cpu.yml), rather than `api-set.yml`, so a refusal is reported. A 403 says which privilege is missing and how to check the token. Other API calls still hide their output, because the token is in the request.
- **The restart happens inside `proxmox_vm`**, before its existing "Start the VM" task, which then starts the VM again.

**The Proxmox node `com` has SSE4.2 and AES, but no AVX2** (checked 2026-11-13 with `grep -o -w 'sse4_2\|avx2\|aes' /proc/cpuinfo`). So `x86-64-v2-AES` is the most a VM can get, short of `host`. `x86-64-v3` and `x86-64-v4` need AVX2, and VMs given them wouldn't start. Software that requires AVX2 can't run on this node in any VM.

## 1. Target

```yaml
# proxmox/vars.yaml
vm_cpu_type: x86-64-v2-AES      # every VM, unless its host entry says otherwise

# networks/lab.yaml
hosts:
  - name: ws
    type: workstation
    vm_id: 120
    ip: 10.1.0.10
    cpu: host                   # this VM only
```

- **A new VM** gets its CPU type right after it is cloned, before its first start. Nothing else is needed.
- **An existing VM** with another CPU type gets the new type on its next deploy. Proxmox holds the change as pending until the VM is stopped and started; a reboot from inside the guest doesn't apply it. The deploy says so, and doesn't restart the VM unless asked:

  ```text
  ws (VM 120): CPU type changes from kvm64 to host on the next stop and start.
  Run again with -e proxmox_vm_restart=true to do that now.
  ```

- **`-e proxmox_vm_restart=true`** shuts the VM down cleanly through Proxmox (ACPI), starts it, and carries on with the deploy. The VM is down for its boot time.
- **The template** gets `vm_cpu_type` when `create-template.yaml` makes it. Deploys don't depend on that, since they set the type on every VM themselves.

## 2. CPU types

| Type | Instructions | VM can move to | Use for |
|---|---|---|---|
| `kvm64` (today) | Roughly 2004: no SSE4.2, no AVX | Any host | Nothing. Not allowed by the plan. |
| `x86-64-v2` | SSE4.2, POPCNT, SSSE3 | Any x86-64-v2 host (2009+) | A node without AES-NI. Not needed on `com`. |
| `x86-64-v2-AES` | v2 + AES-NI | Any x86-64-v2 host with AES-NI | The default. Enough for Bun, Claude Code and most prebuilt software. |
| `x86-64-v3` | v2 + AVX, AVX2, BMI, FMA | Any x86-64-v3 host (Intel 2013+, AMD 2015+) | **Not on `com`:** it has no AVX2. Not allowed by the plan. |
| `x86-64-v4` | v3 + AVX-512 | AVX-512 hosts only | **Not on `com`.** Not allowed by the plan. |
| `host` | Everything the physical CPU has | Only a host with the same CPU | Little gain on `com`: without AVX2, it adds only minor extensions over `x86-64-v2-AES`. |

There is one Proxmox node (`com`), so whether a VM can move to another host doesn't matter today. If a second node is added, `host` VMs can still be moved while stopped. If a node with AVX2 is added, `x86-64-v3` can be added to the allowed list.

A type the physical CPU doesn't support stops the VM from starting. Proxmox reports it then, so the deploy can't check this beforehand. Section 6 covers it.

## 3. Decisions needing approval

| # | Decision | Recommended | Alternative |
|---|---|---|---|
| 1 | Project default | `x86-64-v2-AES`, the most `com` supports short of `host` | `host` everywhere. Barely faster on `com`, and ties every VM to this CPU model. |
| 2 | Per-host override | `cpu:` on any host in a network file. Rarely needed on `com`, but ready for another node. | No override: one type for every VM. Simpler, until a second node arrives. |
| 3 | Allowed values | `host`, `x86-64-v2`, `x86-64-v2-AES`. Validation rejects anything else, including `kvm64`, and `x86-64-v3`/`v4`, with a message that `com` has no AVX2. | Any Proxmox CPU model name. Then validation can't catch typos, or types that won't start on `com`. |
| 4 | Existing VMs | Set the type on every deploy, and restart only with `-e proxmox_vm_restart=true` | Restart automatically when the type changes. Simpler, but a redeploy for an unrelated change would take a service down unexpectedly. |
| 5 | Restarting | Clean shutdown through Proxmox, with a 120 s timeout, then start. If the guest doesn't shut down in time, fail and say so. | Fall back to a hard stop after the timeout. Quicker, but risks data on the postgres, gitea, garage and nats data disks. |
| 6 | Pending changes in reports | `deploy-network.yaml` lists every VM still waiting for a restart at the end | Only the per-host message |

## 4. How it works

### Setting the type

In [roles/proxmox_vm](../../roles/proxmox_vm/tasks/main.yml), a new input `proxmox_vm_cpu_type` (from `vm.cpu`, which defaults to `vm_cpu_type`):

1. **New clone:** set `cpu` through the existing [api-set.yml](../../roles/proxmox_vm/tasks/api-set.yml) right after cloning, before "Start the VM". It takes effect on the first boot.
2. **Existing VM:** read `cpu` from the config the role already reads (`proxmox_vm_existing.config.cpu`). If it differs from the wanted type, set it through `api-set.yml`. A running VM then shows it as pending.
3. **Pending check:** read `/nodes/<node>/qemu/<vmid>/pending`. Any `cpu` entry with a `pending` value means the change hasn't been applied yet. This also catches a change made earlier, or by hand, that is still waiting for a restart.
4. **Restart**, only with `-e proxmox_vm_restart=true` and a pending CPU change: `proxmox_kvm state: stopped` with `force: false` and `timeout: 120`, then `state: started`. This happens before placement, so the rest of the deploy finds the VM as usual. Placement already waits for SSH.
5. Set the fact `proxmox_vm_cpu_pending` (true or false) for reporting.

Proxmox stores an empty `cpu` as `kvm64`, so a missing `cpu` key counts as `kvm64` when comparing.

### Validation

In [network_config.py](../../plugins/filter/network_config.py):

- `cpu` is added to `HOST_KEYS`. `_Checker.check_host` checks it against the allowed list (decision 3).
- `network_config_inventory` adds `cpu` to each host: the host's `cpu`, else `vm_cpu_type`. `vm_cpu_type` is passed in, as `template_vm_id` and `template_ip` are today.
- `vm_cpu_type` in `proxmox/vars.yaml` is checked the same way, in `network_config`'s main tasks, so a typo there stops every deploy before anything changes.

### Template

[create-template.yaml](../../proxmox/scripts/create-template.yaml) passes `cpu: "{{ vm_cpu_type }}"` to `proxmox_kvm`. The existing template, VM 110, can be updated with `qm set 110 --cpu x86-64-v2-AES`. It isn't required, because deploys set the type on every clone.

### Reporting

- Per host, as in section 1, after `proxmox_vm` runs.
- At the end of [deploy-network.yaml](../../playbooks/deploy-network.yaml), a list of the network's VMs whose CPU change is still pending, with the command that applies them (decision 6).
- The network diagrams don't show the CPU type. It isn't about the network.

### Permissions

Changing `cpu` needs the Proxmox privilege `VM.Config.CPU`. Stopping and starting needs `VM.PowerMgmt`. Both are in the `PVEVMAdmin` role. If the API token's role is narrower, the first deploy fails with a 403 on the config change. [README.md](../../README.md)'s list of token permissions gets both privileges.

## 5. Phases

Each phase leaves the repo working, and the unit tests pass after each one.

### Phase 1: Setting and validation

- `vm_cpu_type` in `proxmox/vars.yaml`, `cpu` in network files, validation, and `cpu` in the inventory.
- Tests:
  - `cpu` is accepted for each allowed value, and rejected for `kvm64`, `qemu64`, `x86-64-v3`, `x86-64-v4`, `Host` and a number.
  - The inventory gets the host's `cpu`, or the default when it isn't set.
  - Repo networks stay valid without `cpu` anywhere.

### Phase 2: Applying it

- `proxmox_vm`: set on clone, set on existing VMs, the pending check, and `-e proxmox_vm_restart=true`.
- `create-template.yaml` sets the type.
- A filter `proxmox_cpu_pending(pending_entries)` reads the `/pending` response. It gets unit tests with sample responses: no change, `cpu` pending, `cpu` deleted (back to the default), and other keys pending.

### Phase 3: Reporting and docs

- The per-host message, and the pending list at the end of `deploy-network.yaml`.
- Docs:
  - [networks/README.md](../../networks/README.md): a `cpu` row in the host table, and the types table from section 2.
  - [roles/proxmox_vm](../../roles/proxmox_vm/) and the token permissions in [README.md](../../README.md).
  - A new entry in [ARCHITECTURE.md §11](../ARCHITECTURE.md#11-architectural-decisions).

### Phase 4: Live check

1. ~~Confirm `com` supports the default.~~ Done: `aes` and `sse4_2`, no `avx2`.
2. Deploy a new throwaway host: Proxmox shows the type before its first start, and `grep -c sse4_2 /proc/cpuinfo` in the guest is above 0.
3. Redeploy `home.ws` (VM 119, `kvm64` today) without the flag: the pending message appears, and nothing restarts.
4. Run again with `-e proxmox_vm_restart=true`: the VM shuts down cleanly, starts, and the deploy finishes. `claude --version` works.
5. Redeploy with no changes: no message, no restart.
6. Set `cpu: host` on the workstation and repeat steps 3–4.
7. `deploy-network.yaml` on `lab` without the flag: the end-of-run list names every VM still on `kvm64`.

## 6. Risks

- **A VM restart is downtime.** Only `-e proxmox_vm_restart=true` causes one. For a whole network, routers go first (they're first in deploy order), so the network loses its way out for that router's boot time.
- **A type the physical CPU lacks stops the VM from starting.** On `com`, validation prevents that by rejecting `x86-64-v3` and `x86-64-v4`. On another node, the start fails with a Proxmox error naming the missing features. Fix `cpu:` and run again; the VM's disk isn't affected.
- **Software that needs AVX2 can't run on `com` at all**, whatever the CPU type. Examples include some prebuilt machine-learning wheels, such as TensorFlow, and some database and compression builds. Such software has to be built without AVX2, or run on other hardware.
- **A guest that ignores ACPI shutdown** hits the 120 s timeout, and the deploy fails without a hard stop (decision 5). Stop it in Proxmox and run again.
- **`host` ties a VM to this CPU model.** Moving it to a different node later means stopping it first, or changing its type.
- **Nothing breaks on its own today.** VMs stay on `kvm64` until a deploy sets the new type and they're restarted, so this can be rolled out one VM at a time.
