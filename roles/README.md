# Roles

Two kinds of role live here:

- **Host type roles**, one per value of `type:` in a network file: `webserver`, `postgres`, `gitea`, `garage`, `router`, `proxy`, `ldap` and `nats`. Each holds the NixOS configuration for that kind of VM and the steps that set up its service. Each has its own README describing its settings.
- **Shared roles**, used by every deploy:

| Role | What it does |
|---|---|
| `network_config` | Reads and checks the network files, and adds hosts to the inventory |
| `host_deploy` | Deploys one host: runs the steps below, calling into its host type role |
| `proxmox_vm` | Clones the template, or updates an existing VM, and adds its data disk and network cards |
| `proxmox_vm_remove` | Deletes a VM and its disks |
| `nixos_base` | Finds the VM, checks it's the right one, installs `common.nix` and `network.nix`, formats the data disk, and switches to the new configuration |
| `isolated_bridge` | Creates and removes the Proxmox bridges of isolated networks |
| `network_verify` | Checks the whole network after a deploy. See its [README](network_verify/README.md) |
| `dotenv` | Reads a `secrets/<network>/<host>.env` file |

## Adding a host

A new VM of an existing type needs no new code. Add an entry under `hosts:` in its network file, with a `name`, `type`, `vm_id` and `ip` (and a `data_disk` for the types that need one), add its secrets file if the type has one, then check and deploy it:

```bash
source proxmox/.env
ansible-playbook playbooks/validate-network.yaml
ansible-playbook playbooks/deploy-host.yaml -e network=lab -e host=<name>
```

[networks/README.md](../networks/README.md#hosts) lists every setting, and the type's README lists its `settings:` and its secrets file.

## Adding a host type

A host type is a role named after the type. `host_deploy` includes it by that name, so the role's name, the `type:` in the network files, and the name in the validator must all match.

The [webserver](webserver/) role is the smallest complete example. [nats](nats/) is a fuller one, with settings, a secrets file and a data disk; the commit that added it (`d058e6f`) touched every file listed below.

### Files in the role

```text
roles/<type>/
  README.md                 what it runs, its settings, its secrets, how to reach it
  defaults/main.yml         settings and their defaults
  env.example               the secrets file, if it needs one
  files/configuration.nix   the VM's NixOS configuration
  templates/<type>.nix.j2   parts of the configuration made from settings, if any
  tasks/prepare.yml         required
  tasks/configure.yml       required
  tasks/verify.yml          required
  tasks/ports.yml           required
```

### The four task files

`host_deploy` runs these in this order, for one VM at a time:

| File | Runs on | Its job |
|---|---|---|
| `tasks/prepare.yml` | localhost, before anything changes | Read the secrets file and check secrets and settings. Fail here, with a message that says which file and setting to fix, rather than halfway through a deploy. Facts set here are available to the later steps. Can be just `[]`. |
| `tasks/configure.yml` | the VM, as root | Install the configuration and switch to it (see below), then set up anything the service needs after it starts. |
| `tasks/verify.yml` | localhost | Check the service answers on its final address, and print how to reach it. |
| `tasks/ports.yml` | localhost, from `network_verify` | Set `verify_expected_ports` to the TCP ports the VM may listen on, other than SSH. Anything else listening is reported as a problem. Ports bound only to loopback don't count. |

Between `prepare` and `configure`, the shared roles create or update the VM and find it, so `configure` always starts on a running VM that's been checked to be the right one.

### configure.yml

Every `configure.yml` follows the same outline:

```yaml
- name: Install the shared NixOS configuration
  ansible.builtin.include_role:
    name: nixos_base
  vars:
    nixos_base_hostname: "{{ vm.name }}"
    nixos_base_data_disk_serial: <type>-data   # only with a data disk

# Secrets and generated .nix files go here, before the switch.

- name: Install <type> NixOS configuration
  ansible.builtin.copy:
    src: configuration.nix
    dest: /etc/nixos/configuration.nix
    mode: "0644"

- name: Switch to the configuration and move to the <type> address
  ansible.builtin.include_role:
    name: nixos_base
    tasks_from: switch
```

The switch can move the VM to a new address and bridge. Tasks after it run on the VM's final address.

### configuration.nix

It imports the files the deploy puts next to it, plus any it generates:

```nix
imports = [
  ./hardware-configuration.nix
  ./common.nix      # users, SSH and other basics shared by every VM
  ./network.nix     # host name and static address, made from the network file
  ./<type>.nix      # from templates/<type>.nix.j2, if the role has one
];
```

Keep it in this repository's style:

- Open the service's ports in `networking.firewall.allowedTCPPorts`. The firewall is on, and SSH is already open.
- Keep secrets out of the Nix store, which every user on the VM can read. Write them to a root-only file in `configure.yml` and point the service at it, as `nats` does with `EnvironmentFile`.
- Put anything that changes with settings in a template, and keep `configuration.nix` a plain file.

### Settings

A host's `settings:` block is `vm.settings`. Merge it over the role's defaults in `defaults/main.yml`, then give each setting a short name for the tasks and templates:

```yaml
<type>_settings_defaults:
  port: 4222

<type>_settings: "{{ <type>_settings_defaults | combine(vm.settings, recursive=true) }}"
<type>_port: "{{ <type>_settings.port }}"
```

Check them in `prepare.yml`. Unknown keys aren't rejected by the validator.

### Secrets

Read `secrets/<network>/<host>.env` in `prepare.yml` with the `dotenv` role, which fails with your hint if the file is missing:

```yaml
- name: Read the secrets file
  ansible.builtin.include_role:
    name: dotenv
  vars:
    dotenv_path: "{{ role_path }}/../../secrets/{{ vm.network.name }}/{{ vm.name }}.env"
    dotenv_missing_hint: "Copy roles/<type>/env.example there and fill it in."
```

The values are in `dotenv_values`. Add `no_log: true` to any task that handles them. Ship an `env.example` with placeholder values, and have `prepare.yml` refuse the placeholders.

### Data disk

A type that keeps data on its own disk gets one when its host has `data_disk:`. The disk's serial is `<type>-data`, so on the VM it is `/dev/disk/by-id/scsi-0QEMU_QEMU_HARDDISK_<type>-data`. Pass that serial to `nixos_base` (above) to format it, mount it in `configuration.nix` with `options = [ "nofail" ]`, and make the service require the mount, so it fails rather than writing to the root disk.

### What the tasks can use

| Variable | Meaning |
|---|---|
| `vm.name`, `vm.type`, `vm.vm_id` | From the network file |
| `vm.settings` | The host's `settings:` block, or `{}` |
| `vm.network.name`, `vm.network.domain`, `vm.network.type` | Its network |
| `vm.expose` | Its port forwards, each with `port` and `wan_port` |
| `vm.dns_name` | `<name>.<domain>` on an isolated network, otherwise empty |
| `vm.data_disk.size_gb` | Size of its data disk, if it has one |
| `final.ip` | Its address after the switch |
| `final.via_router` | The router to go through to reach it, or empty on a home network |
| `nixlab.networks[vm.network.name].router_wan_ip` | Where its port forwards are, on an isolated network |

On an isolated network only the router can reach the VM, so run checks in `verify.yml` with `delegate_to: "{{ final.via_router or 'localhost' }}"`.

### Outside the role

| File | Change |
|---|---|
| `plugins/filter/network_config.py` | Add the type to `HOST_TYPES`. If it needs a data disk, add it to the list that requires `data_disk`. |
| `tests/test_network_config.py` | A test for any new check, such as the required data disk |
| `networks/README.md` | The type in the `type` row, and in the `data_disk` row if it needs one |
| `secrets/README.md` | A row for its secrets file, if it has one |
| `README.md` | A line in the list of host types, and in **Services** at the top |

A web interface needs nothing extra to be served by the proxy: hosts list it under `proxy:` in the network file.

### Trying it out

1. Run the tests: `.venv/bin/python -m unittest discover -s tests`.
2. Add a host of the new type to a throwaway network, such as a copy of [networks/examples/test.yaml](../networks/examples/test.yaml), and run `playbooks/validate-network.yaml`.
3. Deploy it with `playbooks/deploy-host.yaml`, then deploy it again. The second run should change nothing important and still pass.
4. Run `playbooks/verify-network.yaml` to check the VM listens only on the ports in `ports.yml`.
