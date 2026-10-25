# NixOS on Proxmox

Builds a NixOS template on Proxmox and deploys VMs from it.

One command, `./bootstrap.sh`, builds a custom NixOS installer ISO in Docker, uploads it to Proxmox, installs NixOS onto VM 110, checks that the installed system boots, and converts VM 110 into a template. Playbooks under `hosts/` then clone the template into individual servers.

## Repository layout

| Path                         | Purpose                                                       |
| ---------------------------- | ------------------------------------------------------------- |
| `bootstrap.sh`               | Builds the ISO and creates the template, end to end           |
| `flake.nix`                  | Nix definitions, including the installer ISO                  |
| `installer/configuration.nix`| The installer ISO's NixOS configuration                       |
| `modules/common.nix`         | Base configuration shared by the template and every VM        |
| `proxmox/vars.yaml`          | Proxmox host, VM size, IPs and other bootstrap settings       |
| `proxmox/bootstrap.yaml`     | Runs the three template playbooks below in order              |
| `proxmox/scripts/`           | `upload-iso.yaml`, `create-template.yaml`, `install-nix.yaml` |
| `hosts/<name>/`              | Configuration and deploy playbook for each VM                 |
| `Dockerfile`, `start_container.sh` | Nix build container                                     |

## Prerequisites

On the workstation:

- **Docker**, to build the ISO. Nix is not needed on the workstation.
- **Ansible** with the Proxmox modules. The bootstrap uses `.venv/` if it exists:

  ```bash
  uv venv .venv
  uv pip install --python .venv/bin/python ansible proxmoxer requests requests_toolbelt
  .venv/bin/ansible-galaxy collection install community.proxmox community.general ansible.posix
  ```

- **Two SSH key pairs**, kept on the workstation:

  ```bash
  ssh-keygen -t ed25519 -f ~/.ssh/nixos-installer    # logs in as root on the installer ISO
  ssh-keygen -t ed25519 -f ~/.ssh/nixos-deployment   # logs in as admin on installed systems
  ```

  Only the public keys go into the ISO and the installed systems. Never put a private key in the repository, the ISO or the Docker image.

On Proxmox:

- An API token for `ansible@pve` with the ID `automation`, allowed to manage VMs and upload ISOs to the `local` storage.

## Configuration

`bootstrap.sh` reads these variables from the environment, or from `proxmox/.env` if it exists (`.env` is gitignored):

```bash
export PROXMOX_TOKEN_SECRET='<api token secret>'
export NIXOS_INSTALLER_KEY="$HOME/.ssh/nixos-installer"
export NIXOS_INSTALLER_PUBLIC_KEY="$HOME/.ssh/nixos-installer.pub"
export NIXOS_DEPLOYMENT_PUBLIC_KEY="$HOME/.ssh/nixos-deployment.pub"
export NIXOS_DEPLOYMENT_PRIVATE_KEY="$HOME/.ssh/nixos-deployment"
```

The key variables are file paths. The Proxmox host, node, VM ID, IPs, VM size and storage names are in `proxmox/vars.yaml`.

## Building the template

```bash
./bootstrap.sh
```

The script stops at the first failure. In order, it:

1. Checks that Docker, Ansible, the Ansible collections, the variables above and the key files are all present.
2. Builds the `nixos-lab` Docker image.
3. Builds the installer ISO in the container and copies it to `build/nixos-installer-<hash>.iso`. The hash comes from the Nix build, so a changed configuration or key gives a new name.
4. Uploads the ISO to Proxmox. The upload is skipped if an ISO with that name is already there.
5. Creates VM 110 with the ISO attached and boots it into the installer.
6. Waits for the installer's SSH, then over SSH:
   - partitions `/dev/sda` with a BIOS boot partition and an ext4 root partition
   - generates `hardware-configuration.nix`
   - installs `modules/common.nix` and a `configuration.nix` holding the static IP
   - runs `nixos-install`
7. Stops the VM, detaches the ISO and boots the installed system.
8. Logs in as `admin` with the deployment key. Only the installed system has that user, so this proves the VM booted from its disk and not the ISO.
9. Shuts the VM down and converts it into a template.

### Options

```bash
./bootstrap.sh --force     # destroy VM 110 first if it already exists
./bootstrap.sh -- -vv      # pass extra arguments to ansible-playbook
```

Without `--force`, the script refuses to touch an existing VM 110. Proxmox will not delete a template that still has linked clones, such as the webserver, so remove those clones before using `--force`.

### Running a single stage

Each playbook in `proxmox/scripts/` can run on its own once an ISO is built. Pass the ISO path:

```bash
ansible-playbook proxmox/scripts/install-nix.yaml -e installer_iso="$PWD/build/nixos-installer-<hash>.iso"
```

## Deploying VMs from the template

Each VM has its own folder under `hosts/`, with a playbook and a README that explains how to deploy and change it:

- [webserver](hosts/webserver/README.md): nginx serving static files
- [postgres](hosts/postgres/README.md): PostgreSQL on a separate data disk, with optional AdventureWorks sample data

A host playbook clones the template, boots the clone on the template's IP, installs the host's NixOS configuration, and runs `nixos-rebuild switch`. The clone then moves to its own IP. Each host's hostname and IP are set in its `vars.yaml`; the playbook generates `/etc/nixos/network.nix` from them using `modules/network.nix.j2`.

## Network addressing

Static addresses must stay outside the DHCP pool.

| IP             | System                                                    |
| -------------- | --------------------------------------------------------- |
| `192.168.1.1`  | gateway and DNS                                  |
| `192.168.1.10` | Installer ISO and the template, on VM 110 (never at the same time). New clones also boot here first. |
| `192.168.1.11` | webserver (VM 111)                                        |
| `192.168.1.12` | postgres (VM 112)                                         |

Because every new clone starts on `.10`, deploy one VM at a time.

## Notes

### SSH host keys

The installer ISO and the installed template both answer on `192.168.1.10` but have different SSH host keys. `bootstrap.sh` removes the `.10` entry from `~/.ssh/known_hosts` before each switch, then accepts the new key on first connect. Clones keep the template's host keys.

If a manual SSH connection reports `REMOTE HOST IDENTIFICATION HAS CHANGED` after a rebuild, remove the old entry:

```bash
ssh-keygen -f ~/.ssh/known_hosts -R 192.168.1.10
```

### The installer key is read at build time

`installer/configuration.nix` reads the installer's public key from the `NIXOS_INSTALLER_AUTHORIZED_KEY` environment variable. `bootstrap.sh` fills it from the file in `NIXOS_INSTALLER_PUBLIC_KEY`. Reading the environment from a flake requires `--impure`, so a plain `nix build` or `nix flake check` of the installer fails with an assertion asking for the key.

### `HOME=/root` for `nixos-install`

The `nixos-install` task sets `HOME=/root`. Without it, the command fails under Ansible with misleading hostname-resolution errors, even though it works when run interactively and the installer can reach `cache.nixos.org`.

### Build container

To work in the Nix container by hand:

```bash
./start_container.sh
nix build --impure .#nixosConfigurations.installer.config.system.build.isoImage
```

`bootstrap.sh` keeps the container's Nix store in a Docker volume named `nixos-lab-nix-<image id>`, so later builds reuse downloads. A new volume is created whenever the image changes. Clear out old ones with `docker volume prune`.
