# PostgreSQL server

A NixOS VM running PostgreSQL, with its database files on a separate data disk. It can optionally load the [AdventureWorks](https://github.com/mwgolden/adventure-works-postgres) sample database.

| Setting    | Value                                         |
| ---------- | --------------------------------------------- |
| VM         | 112, `postgres`                               |
| IP         | `192.168.1.12`                                |
| PostgreSQL | 17, port 5432                                 |
| Data disk  | 20 GB, mounted at `/var/lib/postgresql`        |
| Logins     | Password logins from `192.168.1.0/24`          |

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

Shared settings (Proxmox host, node, template, gateway, DNS) come from `proxmox/vars.yaml`. The hostname and IP file is generated from `modules/network.nix.j2`.

## Admin login

The database admin login is in `hosts/postgres/.env`:

```bash
POSTGRES_ADMIN_USER=pgadmin
POSTGRES_ADMIN_PASSWORD=...
```

If `.env` doesn't exist, copy `.env.example` to `.env` and set a password. The user name may contain lowercase letters, digits and underscores.

The playbook creates this user as a PostgreSQL superuser and sets its password on every run. To change the password, edit `.env` and re-run the playbook. The password is sent to the VM over SSH and is kept out of Ansible's output and out of the NixOS configuration.

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
4. Runs `nixos-rebuild build`, so any error shows up before anything changes, then `nixos-rebuild switch`. The VM moves to `192.168.1.12`.
5. Checks that the data disk is mounted at `/var/lib/postgresql` and that PostgreSQL is running.
6. Creates the admin user from `.env`.
7. Loads AdventureWorks, if enabled.
8. Checks that port 5432 is reachable from your machine, and prints how to connect.

Because new clones use the template's IP, deploy one VM at a time.

## Connecting

```bash
psql -h 192.168.1.12 -U pgadmin -d postgres
```

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

It then stops the VM, deletes it, and removes `192.168.1.12` from your known_hosts. It refuses to delete VM 112 if that VM has a name other than `postgres`, and does nothing if the VM doesn't exist.
