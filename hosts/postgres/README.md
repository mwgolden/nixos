# PostgreSQL server

A NixOS VM running PostgreSQL, with its database files on a separate data disk. It can optionally load the [AdventureWorks](https://github.com/mwgolden/adventure-works-postgres) sample database.

| Setting    | Value                                         |
| ---------- | --------------------------------------------- |
| VM         | 112, `postgres`                               |
| Network    | `home` (`vmbr0`), or `isolated` behind the [router](../router/README.md) |
| IP         | `192.168.1.12` on the home network, `10.1.0.12` on the isolated network |
| PostgreSQL | 17, port 5432                                 |
| Data disk  | 20 GB, mounted at `/var/lib/postgresql`        |
| Logins     | Password logins from `192.168.1.0/24` and `10.1.0.0/24` |

These values come from `vars.yaml`.

## Files

| File                | Purpose                                                                 |
| ------------------- | ----------------------------------------------------------------------- |
| `vars.yaml`         | VM ID, IP, data disk size, PostgreSQL version and port, allowed networks, AdventureWorks |
| `.env`              | Database admin user and password (gitignored)                           |
| `.env.example`      | Template for `.env`                                                     |
| `configuration.nix` | NixOS configuration: PostgreSQL service and the data disk mount         |
| `postgres.nix.j2`   | Template for the generated settings: version, port, allowed networks, firewall |
| `postgres.yaml`     | Deploy playbook                                                         |
| `destroy.yaml`      | Deletes the VM and its data disk                                        |
| `users/`            | Database users and their access per schema                              |

Shared settings (Proxmox host, node, template, gateway, DNS) come from `proxmox/vars.yaml`. The hostname and IP file is generated from `modules/network.nix.j2`.

## Admin login

The database admin login is in `hosts/postgres/.env`:

```bash
POSTGRES_ADMIN_USER=pgadmin
POSTGRES_ADMIN_PASSWORD=...
```

If `.env` doesn't exist, copy `.env.example` to `.env` and set a password. The user name may contain lowercase letters, digits and underscores.

The playbook creates this user as a PostgreSQL superuser and sets its password on every run. To change the password, edit `.env` and re-run the playbook. The password is sent to the VM over SSH and is kept out of Ansible's output and out of the NixOS configuration.

## Database users

To create users and give them access to schemas, see [users/README.md](users/README.md). Each user can combine access levels (read, write, create, execute) on any number of schemas with built-in roles such as `pg_monitor`.

## Deploying

The NixOS template must exist first (run `./bootstrap.sh` from the repo root). Then, from the repo root:

```bash
source proxmox/.env
ansible-playbook hosts/postgres/postgres.yaml
```

`proxmox/.env` provides the Proxmox token and the deployment SSH key. The playbook reads `hosts/postgres/.env` itself.

On a first run the playbook:

1. Clones the template into VM 112, adds the data disk (scsi1) and starts the VM. The clone boots on the template's IP, `192.168.1.10`.
2. Formats the data disk as ext4.
3. Installs the NixOS configuration into `/etc/nixos`: `common.nix`, plus `network.nix` and `postgres.nix` generated from `vars.yaml`, plus `configuration.nix`.
4. Runs `nixos-rebuild build`, so any error shows up before anything changes, then `nixos-rebuild switch`. The VM moves to its own IP. For the isolated network, the playbook also moves the VM's network card to `vmbr1` and reconnects through the router.
5. Checks that the data disk is mounted at `/var/lib/postgresql` and that PostgreSQL is running.
6. Creates the admin user from `.env`.
7. Loads AdventureWorks, if enabled.
8. Checks that port 5432 is reachable, from your machine or, on the isolated network, from the router. Then prints how to connect.

Because new clones use the template's IP, deploy one VM at a time.

## Connecting

On the home network:

```bash
psql -h 192.168.1.12 -U pgadmin -d postgres
```

On the isolated network, VMs on the same LAN connect to `10.1.0.12`. From home, add a [router port forward](../router/README.md#port-forwards) and connect to the router's address:

```yaml
router_port_forwards:
  - name: postgres
    proto: tcp
    wan_port: 5432
    lan_ip: "10.1.0.12"
```

```bash
psql -h 192.168.1.13 -U pgadmin -d postgres
```

Forwarded connections keep your home address, so `192.168.1.0/24` in `postgres_allowed_networks` still applies to them.

On the VM itself, the `postgres` system user can connect without a password:

```bash
sudo -u postgres psql
```

## Data disk

The database files are on their own disk (scsi1, serial `postgres-data`), separate from the operating system. The size is `postgres_data_disk_gb` in `vars.yaml`.

- **Growing:** raise `postgres_data_disk_gb` and re-run the playbook. It grows the disk in Proxmox, then grows the filesystem while PostgreSQL keeps running.
- **Shrinking isn't possible.** Proxmox can't shrink disks, so the playbook stops with an error if the value is smaller than the current disk.
- **Re-runs never wipe it.** The disk is only formatted if it has no filesystem yet.

If the disk is ever missing at boot, the VM still starts and you can SSH in, but PostgreSQL won't start. That stops it from writing a new, empty database onto the system disk.

## AdventureWorks sample database

To load it, set this in `vars.yaml` and run the playbook:

```yaml
adventureworks_enabled: true
```

The playbook downloads the repo on the VM at the commit in `adventureworks_version`, creates the `Adventureworks` database owned by the admin user, and runs `install.sql`. The import takes a few minutes, and the download is deleted afterwards.

- It only loads the data if the database doesn't exist yet, so re-runs never overwrite it. To reload it, drop the database and re-run.
- If the import fails, the playbook removes the partly loaded database so the next run starts fresh.
- Some `\copy` lines in that repo's `install.sql` point to `X.csv` instead of `./data/X.csv`. The playbook links the CSV files next to `install.sql` so both forms work. If you fix the paths in the repo, update `adventureworks_version` to the new commit.

## Home or isolated network

`postgres_network` in `vars.yaml` decides where the VM lives:

- `home`: on `vmbr0` at `192.168.1.12`.
- `isolated`: on the router's isolated LAN at `10.1.0.12` (`postgres_isolated_ip`). It reaches the internet through the router, but not the home network. Deploy the router first.

To deploy straight onto the isolated network, set `postgres_network: "isolated"` before the first run. To move a deployed server, change the setting and re-run `postgres.yaml`, or move it without redeploying:

```bash
ansible-playbook hosts/move-network.yaml -e host=postgres -e network=isolated
ansible-playbook hosts/move-network.yaml -e host=postgres -e network=home
```

`move-network.yaml` only changes the network settings and keeps the data disk and databases as they are. It updates `postgres_network` in `vars.yaml` to match. The users playbook (`users/users.yaml`) reads `postgres_network` too, and reaches an isolated server through the router.

## Making changes

Edit the files here and re-run the playbook. When VM 112 already exists, the playbook updates it in place on its own IP and doesn't re-clone it.

- **Allowed networks or port:** change `postgres_allowed_networks` or `postgres_port` in `vars.yaml`. The firewall follows the port.
- **PostgreSQL version:** `postgres_version` can be 16, 17 or 18. Changing it on an existing server starts a new, empty data directory next to the old one (for example `/var/lib/postgresql/18`). It doesn't migrate your data, so dump and restore first.
- **NixOS settings:** edit `configuration.nix`. Leave the hostname, IP and PostgreSQL version out of it; they belong in `vars.yaml`.

The playbook refuses to configure VM 112 if it exists under a name other than `postgres`.

## Linked clone

By default the VM is a linked clone (`postgres_full_clone: false`). It's created quickly and uses little disk, but Proxmox won't delete the template while the clone exists, so `./bootstrap.sh --force` fails. Set `postgres_full_clone: true` before the first deploy to make an independent copy instead. The data disk is always a separate, independent disk.

## Removing the server

```bash
source proxmox/.env
ansible-playbook hosts/postgres/destroy.yaml
```

This permanently deletes VM 112, its data disk and every database on it. The playbook asks you to type `postgres` to confirm. To skip the prompt in a script, pass `-e confirm_destroy=postgres`.

It then stops the VM, deletes it, and removes `192.168.1.12` and `10.1.0.12` from your known_hosts. It refuses to delete VM 112 if that VM has a name other than `postgres`, and does nothing if the VM doesn't exist.
