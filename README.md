# NixOS on Proxmox

Builds a NixOS template on Proxmox and deploys VMs from it.

One command, `./bootstrap.sh`, builds a custom NixOS installer ISO in Docker, uploads it to Proxmox, installs NixOS onto VM 110, checks that the installed system boots, and converts VM 110 into a template. `playbooks/deploy-host.yaml` then clones the template into the servers described in `networks/`.

## Repository layout

| Path                         | Purpose                                                       |
| ---------------------------- | ------------------------------------------------------------- |
| `bootstrap.sh`               | Builds the ISO and creates the template, end to end           |
| `flake.nix`                  | Nix definitions, including the installer ISO                  |
| `installer/configuration.nix`| The installer ISO's NixOS configuration                       |
| `modules/common.nix`         | Base configuration shared by the template and every VM        |
| `proxmox/vars.yaml`          | Proxmox host, VM size, IPs and other bootstrap settings       |
| `proxmox/bootstrap.yaml`     | Runs the three template playbooks below in order              |
| `proxmox/scripts/`           | `upload-iso.yaml`, `create-template.yaml`, `install-nix.yaml`, and `isolated-bridge.yaml` for the isolated network |
| `ansible.cfg`                | Ansible settings. Run playbooks from the repository root so it is used |
| `networks/`                  | One file per network and the VMs on it. See [networks/README.md](networks/README.md) |
| `playbooks/validate-network.yaml` | Checks the network files, and checks them against Proxmox |
| `plugins/filter/`, `tests/`  | Network file checks and their tests: `.venv/bin/python -m unittest discover -s tests` |
| `roles/`                     | One role per host type (its NixOS configuration and service setup), plus shared roles: creating and removing VMs, reading the network files, finding a VM and switching it to its network |
| `playbooks/`                 | `deploy-network.yaml`, `deploy-host.yaml`, `destroy-network.yaml`, `destroy-host.yaml`, `validate-network.yaml` and `postgres-users.yaml` |
| `secrets/`                   | Host passwords and keys, gitignored. See [secrets/README.md](secrets/README.md) |
| `Dockerfile`, `start_container.sh` | Nix build container                                     |

## Prerequisites

On the workstation:

- **Docker**, to build the ISO. Nix is not needed on the workstation.
- **Ansible** with the Proxmox modules. The bootstrap uses `.venv/` if it exists, and the other playbooks should be run with it too:

  ```bash
  uv venv .venv
  uv pip install --python .venv/bin/python ansible proxmoxer requests requests_toolbelt netaddr
  .venv/bin/ansible-galaxy collection install community.proxmox community.general ansible.posix ansible.utils
  ```

- **Two SSH key pairs**, kept on the workstation:

  ```bash
  ssh-keygen -t ed25519 -f ~/.ssh/nixos-installer    # logs in as root on the installer ISO
  ssh-keygen -t ed25519 -f ~/.ssh/nixos-deployment   # logs in as admin on installed systems
  ```

  Only the public keys go into the ISO and the installed systems. Never put a private key in the repository, the ISO or the Docker image.

On Proxmox:

- An API token for `ansible@pve` with the ID `automation`, allowed to manage VMs and upload ISOs to the `local` storage. Setting VM tags and notes uses `VM.Config.Options`, which managing VMs normally includes. Creating or removing an isolated bridge also needs `Sys.Modify` on `/nodes/com`.

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

Each network is described by a file in [networks/](networks/README.md): its bridge, subnet and gateway, and the VMs on it. Today there are two:

- [networks/home.yaml](networks/home.yaml): webserver, gitea and garage, directly on the home LAN.
- [networks/lab.yaml](networks/lab.yaml): the router and postgres, on the isolated bridge.

Check the files, then deploy a whole network, or one host:

```bash
source proxmox/.env
ansible-playbook playbooks/validate-network.yaml
ansible-playbook playbooks/deploy-network.yaml -e network=lab
ansible-playbook playbooks/deploy-host.yaml -e network=lab -e host=postgres
```

`deploy-network.yaml` deploys the network's hosts one at a time. On an isolated network the router goes first, then the rest in file order, and the run stops at the first host that fails. The router's deploy creates the network's bridge if it doesn't exist yet.

### Which VMs are the project's

Every deploy tags its VM in Proxmox with `nixlab`, `net-<network>` and `type-<type>`. Other tags you add are kept. The playbooks only ever delete VMs carrying `nixlab` and the right `net-` tag, so VMs this project didn't make are safe even if their ID or name is in a file by mistake.

Before deploying, `deploy-network.yaml` (and `validate-network.yaml`) report:

- **Removed from the file:** VMs tagged for the network that no network file lists any more. They're left running unless you prune:

  ```bash
  ansible-playbook playbooks/deploy-network.yaml -e network=lab -e prune=true
  ```

  This asks you to type the network name (or takes `-e confirm_prune=lab`), deletes them, routers last, and then deploys. If a removed VM still holds an address that the file gives another host, the deploy stops until you prune or change the address.
- **Moved:** VMs tagged for this network but now listed in another network's file. They move when you deploy that network, and are never pruned.
- **Not yet tagged:** VMs deployed before tagging existed. Their next deploy tags them. Until then, nothing deletes them.

To delete a whole network, routers last, and optionally its bridge once no VM uses it:

```bash
ansible-playbook playbooks/destroy-network.yaml -e network=lab -e remove_bridge=true
```

It asks you to type the network name. The network file stays, so deploying it again recreates everything.

The deploy:

1. Checks every network file and compares them with Proxmox.
2. Clones the template if the VM doesn't exist, and adds its data disk and network cards.
3. Finds the VM. A new clone boots on the template's IP. An existing VM is found at the address its last deploy recorded in its Proxmox notes.
4. Checks that the VM's MAC address matches Proxmox's before changing anything.
5. Installs its NixOS configuration and runs `nixos-rebuild switch`, which moves it to its own IP.
6. Records the new address in its Proxmox notes, as `nixlab-address: <ip> on <bridge>`, then checks that its service answers. On an isolated network it also records the VM's DNS name, as `nixlab-dns: postgres.lab.home.arpa`. That name only works from VMs on that network. Other lines in the notes are kept.

Running it again on an existing VM updates it in place. VMs on an isolated network are reached over SSH through that network's router, so deploy the router first.

Each host type is a role in [roles/](roles/), with a README that explains its settings:

- [webserver](roles/webserver/README.md): nginx serving static files
- [postgres](roles/postgres/README.md): PostgreSQL on a separate data disk, with optional AdventureWorks sample data. [Database users](roles/postgres/USERS.md) are managed with `playbooks/postgres-users.yaml`.
- [gitea](roles/gitea/README.md): Gitea Git server on a separate data disk
- [garage](roles/garage/README.md): Garage S3-compatible object storage on a separate data disk
- [router](roles/router/README.md): connects an isolated bridge to the internet with DHCP, NAT and a firewall that blocks the home LAN

Passwords and keys for hosts go in `secrets/<network>/<host>.env`; see [secrets/README.md](secrets/README.md).

To delete a host's VM and all its disks (it asks you to type the name):

```bash
ansible-playbook playbooks/destroy-host.yaml -e network=lab -e host=postgres
```

Remove its entry from the network file too, or the next deploy creates it again. A router can't be deleted while VMs of its network still exist, and only VMs tagged as the project's are deleted.

## Network addressing

Static addresses must stay outside the home router's DHCP pool. Validation checks that no two hosts share an address, and that no host uses the template's address or a network's gateway.

| IP             | System                                                    |
| -------------- | --------------------------------------------------------- |
| `192.168.1.1`  | gateway and DNS                                           |
| `192.168.1.10` | Installer ISO and the template, on VM 110 (never at the same time). New clones also boot here first. |
| `192.168.1.11` | webserver (VM 111)                                        |
| `192.168.1.13` | router (VM 113), WAN side                                 |
| `192.168.1.14` | gitea (VM 114)                                            |
| `192.168.1.15` | garage (VM 115)                                           |

Because every new clone starts on `.10`, the deploy works on one VM at a time.

### Isolated network

`vmbr1` is a bridge with no physical port and no IP on the Proxmox host. Deploying the router creates it if it's missing, and `proxmox/scripts/isolated-bridge.yaml -e bridge=<name>` can create one on its own. The [router](roles/router/README.md) is its only way out:

| IP                          | System                                     |
| --------------------------- | ------------------------------------------ |
| `10.1.0.1`                  | router (VM 113), LAN side: gateway and DNS |
| `10.1.0.12`                 | postgres (VM 112)                          |
| `10.1.0.100` – `10.1.0.199` | DHCP pool                                  |

VMs on `vmbr1` reach the internet but not `192.168.1.0/24` or other private networks. From home, they're reachable only through port forwards on the router, made from each host's `expose:` entries in `networks/lab.yaml`. The router's DNS server answers for the network's hosts, as `postgres` or `postgres.lab.home.arpa`.

With every server on the isolated network, traffic flows like this:

```mermaid
flowchart TB
    internet(("Internet"))

    subgraph home["Home LAN 192.168.1.0/24"]
        gateway["Home gateway and DNS<br/>192.168.1.1"]
        workstation["Workstation<br/>Ansible, SSH, S3 and DB clients"]
    end

    subgraph proxmox["Proxmox host (node com)"]
        vmbr0["vmbr0<br/>bridged to the physical NIC"]

        router["router, VM 113<br/>ens18 WAN 192.168.1.13<br/>ens19 LAN 10.1.0.1<br/>NAT, firewall, DHCP, DNS forwarder"]

        vmbr1["vmbr1, isolated bridge<br/>no physical port, no host IP<br/>10.1.0.0/24, DHCP .100 to .199"]

        subgraph servers["Servers on the isolated LAN"]
            webserver["webserver, VM 111<br/>10.1.0.11, HTTP 80"]
            postgres["postgres, VM 112<br/>10.1.0.12, TCP 5432"]
            gitea["gitea, VM 114<br/>10.1.0.14, HTTP 3000, SSH 22"]
            garage["garage, VM 115<br/>10.1.0.15, S3 3900"]
        end
    end

    internet <--> gateway
    gateway <--> vmbr0
    workstation <--> vmbr0
    vmbr0 <-->|"ens18"| router
    router <-->|"ens19"| vmbr1
    vmbr1 <--> webserver
    vmbr1 <--> postgres
    vmbr1 <--> gitea
    vmbr1 <--> garage

    servers -.->|"outbound to the internet,<br/>NAT through 192.168.1.13"| internet
    servers -.-x|"blocked: 192.168.0.0/16,<br/>172.16.0.0/12, 10.0.0.0/8"| home
    workstation -.->|"SSH to the router on 22,<br/>ProxyJump on to 10.1.0.x"| router
    workstation -.->|"port forwards to the router,<br/>e.g. 192.168.1.13:5432 to 10.1.0.12:5432"| router
```

Solid lines are the physical and virtual links. Dashed lines are what the router's firewall allows or blocks. The router's own SSH is reachable only from the home side; the isolated LAN can use only DHCP, DNS and ping on the router.

## Moving a VM between networks

Move the host's entry from one network file to the other, give it an address in its new network, and deploy it:

```bash
ansible-playbook playbooks/deploy-host.yaml -e network=lab -e host=gitea
```

The deploy finds the VM at the address it recorded last time, changes its address and moves its network card (net0) to the new bridge. Proxmox does that while the VM runs, and the VM keeps its MAC address and disks. The router must be deployed before anything moves onto an isolated network.

If a move is interrupted, run it again. The deploy also looks for the VM at its new address and on the other bridge, moving the card if needed, and finishes the move from wherever the VM is.

To SSH to an isolated VM by hand, add this to `~/.ssh/config`:

```
Host 192.168.1.13 10.1.0.*
  User admin
  IdentityFile ~/.ssh/nixos-deployment

Host 10.1.0.*
  ProxyJump 192.168.1.13
```

Then `ssh 10.1.0.12` goes through the router.

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
