# PostgreSQL server

A NixOS VM running PostgreSQL, with its database files on a separate data disk. It can optionally load the [AdventureWorks](https://github.com/mwgolden/adventure-works-postgres) sample database, and manage [database users](USERS.md).

```yaml
hosts:
  - name: postgres
    type: postgres
    vm_id: 112
    ip: 10.1.0.12
    data_disk:
      size_gb: 20          # mounted at /var/lib/postgresql
      storage: local-lvm
    settings:
      # All optional; these are the defaults.
      version: 17          # 16, 17 or 18
      port: 5432
      # allowed_networks: [home, lab]   # worked out when unset; see below
      adventureworks:
        enabled: false
        database: Adventureworks
```

The defaults, including the AdventureWorks repo and commit, are in [defaults/main.yml](defaults/main.yml).

## Admin login

Copy [env.example](env.example) to `secrets/<network>/<host>.env`, such as `secrets/lab/postgres.env`:

```bash
POSTGRES_ADMIN_USER=pgadmin
POSTGRES_ADMIN_PASSWORD=...
```

The user name may contain lowercase letters, digits and underscores. The deploy creates this user as a superuser and sets its password on every run, so to change it, edit the file and redeploy. The password is sent over SSH and kept out of Ansible's output and the NixOS configuration.

## Deploying

```bash
source proxmox/.env
ansible-playbook playbooks/deploy-host.yaml -e network=lab -e host=postgres
```

Besides the steps every host goes through, the deploy:

1. Adds the data disk (scsi1, serial `postgres-data`) and formats it as ext4 if it has no filesystem yet.
2. Checks the disk is mounted at `/var/lib/postgresql` and PostgreSQL is running.
3. Creates or updates the admin user.
4. Loads AdventureWorks, if enabled.
5. Checks the port accepts connections (from the router, on an isolated network) and prints how to connect.

## Connecting

On a home network:

```bash
psql -h 192.168.1.12 -U pgadmin -d postgres
```

On an isolated network, VMs on it and VPN clients connect to `postgres.lab.home.arpa`. From home, forward the port in the host's entry and redeploy postgres and the router:

```yaml
    expose:
      - port: 5432
```

```bash
psql -h 192.168.1.13 -U pgadmin -d postgres
```

On the VM itself, the `postgres` system user connects without a password: `sudo -u postgres psql`.

## Who may log in

`settings.allowed_networks` lists where password logins over TCP are allowed from, as network names (from `networks/`) or subnets. Left unset, it is:

- the host's own network,
- its router's VPN, if the network has one,
- the upstream network (home), once the host has `expose:` entries, since forwarded connections keep their home address.

The firewall opens the port to everyone who can reach the VM; `pg_hba.conf` decides who may log in.

## Data disk

The database files are on their own disk, separate from the operating system.

- **Growing:** raise `data_disk.size_gb` and redeploy. The disk grows in Proxmox, then the filesystem grows while PostgreSQL keeps running.
- **Shrinking isn't possible.** Proxmox can't shrink disks, so the deploy stops if the size is smaller than the current disk.
- **Redeploys never wipe it.** It is only formatted if it has no filesystem yet.

If the disk is missing at boot, the VM still starts and you can SSH in, but PostgreSQL won't start. That stops it writing a new, empty database onto the system disk.

## AdventureWorks sample database

Set `settings.adventureworks.enabled: true` and redeploy. The deploy downloads the repo on the VM at the commit in `settings.adventureworks.version`, creates the database owned by the admin user, and runs `install.sql`. It takes a few minutes, and the download is deleted afterwards.

- It only loads if the database doesn't exist yet, so redeploys never overwrite it. To reload, drop the database and redeploy.
- If the import fails, the partly loaded database is removed, so the next run starts fresh.
- Some `\copy` lines in that repo's `install.sql` point to `X.csv` instead of `./data/X.csv`. The deploy links the CSV files next to `install.sql`, so both forms work.

## Making changes

Edit the host's entry or the files here and redeploy. An existing VM is updated in place.

- **Port or allowed networks:** change them under `settings:`. The firewall follows the port. If the host is exposed, change its `expose:` port to match.
- **Version:** changing `settings.version` on an existing server starts a new, empty data directory next to the old one (such as `/var/lib/postgresql/18`). It doesn't migrate data, so dump and restore first.
- **NixOS settings:** edit [files/configuration.nix](files/configuration.nix). Leave the hostname, addresses, version and port out; they come from the network file.
- **Address or network:** change `ip`, or move the entry to another network file, and redeploy. The data disk moves with the VM. See [Moving a VM between networks](../../README.md#moving-a-vm-between-networks).

## Files

| File | Purpose |
|---|---|
| `files/configuration.nix` | NixOS configuration: PostgreSQL and the data disk mount |
| `templates/postgres.nix.j2` | Generated settings: version, port, allowed networks, firewall |
| `templates/users.sql.j2` | SQL for [database users](USERS.md) |
| `env.example`, `users-env.example` | Templates for the admin and users' secrets files |
| `tasks/` | `prepare.yml` (secrets), `configure.yml` (disk, switch, admin, AdventureWorks), `verify.yml`, `ports.yml` |

## Removing it

```bash
ansible-playbook playbooks/destroy-host.yaml -e network=lab -e host=postgres
```

This permanently deletes the VM, its data disk and every database on it. It asks you to type the host name. Remove the entry from the network file too, or the next deploy creates it again.
