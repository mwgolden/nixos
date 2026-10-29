# Gitea

> **Moved to network files.** This host is now set up from its entry in [networks/home.yaml](../../networks/home.yaml), and deployed with `playbooks/deploy-host.yaml -e network=home -e host=gitea`. Secrets are in `secrets/home/gitea.env` (see [secrets/README.md](../../secrets/README.md)). The commands below have been updated. Where the text still names an old `vars.yaml` setting, this table shows where that setting is now:
>
> | Old setting | In the network file |
> |---|---|
> | `gitea_vm_id` | `vm_id` |
> | `gitea_vm_name` | `name` |
> | `gitea_full_clone` | `full_clone` |
> | `gitea_ip / gitea_isolated_ip` | ip, in whichever network file the host is in |
> | `gitea_network` | which network file the host is in |
> | `gitea_data_disk_gb` | `data_disk.size_gb` |
> | `gitea_data_disk_storage` | `data_disk.storage` |
> | `gitea_http_port` | `settings.http_port` |
> | `gitea_public_host` | `settings.public_host` |
> | `gitea_public_http_port` | `settings.public_http_port` |
> | `gitea_public_ssh_port` | `settings.public_ssh_port` |
> | `gitea_allow_registration` | `settings.allow_registration` |


A NixOS VM running [Gitea](https://about.gitea.com/), a self-hosted Git server with a web interface. Everything Gitea keeps is on a separate data disk.

| Setting    | Value                                         |
| ---------- | --------------------------------------------- |
| VM         | 114, `gitea`                                  |
| Network    | `home` (`vmbr0`), or `isolated` behind the [router](../router/README.md) |
| IP         | `192.168.1.14` on the home network, `10.1.0.14` on the isolated network |
| Web        | `http://<IP>:3000/`                           |
| Git        | over HTTP, or over SSH as `gitea@<IP>` on port 22 |
| Data disk  | 40 GB, mounted at `/var/lib/gitea`            |
| Database   | SQLite, on the data disk                      |
| Sign-up    | Off: only the admin can add users             |

These values come from `vars.yaml`.

## Files

| File                | Purpose                                                                 |
| ------------------- | ----------------------------------------------------------------------- |
| `vars.yaml`         | VM ID, IPs, network, data disk size, web port, public address, sign-up  |
| `.env`              | Gitea admin user, password and email (gitignored)                       |
| `.env.example`      | Template for `.env`                                                     |
| `configuration.nix` | NixOS configuration: Gitea service and the data disk mount              |
| `gitea.nix.j2`      | Template for the generated settings: addresses, ports, sign-up, firewall |
| `gitea.yaml`        | Deploy playbook                                                         |
| `destroy.yaml`      | Deletes the VM and its data disk                                        |

Shared settings (Proxmox host, node, template, gateway, DNS) come from `proxmox/vars.yaml`. The hostname and IP file is generated from `modules/network.nix.j2`.

## Admin login

The Gitea admin login is in `secrets/home/gitea.env`:

```bash
GITEA_ADMIN_USER=gitadmin
GITEA_ADMIN_PASSWORD=...
GITEA_ADMIN_EMAIL=gitadmin@example.com
```

If `.env` doesn't exist, copy `.env.example` to `.env` and fill it in. The user name can't be `admin`, which Gitea reserves. The password needs at least 8 characters.

The playbook creates this user as a Gitea admin on the first run and sets its password on every run. To change the password, edit `.env` and re-run. Changing the email in `.env` later doesn't change it in Gitea; do that in the web interface. The password is kept out of Ansible's output and the NixOS configuration.

## Deploying

The NixOS template must exist first (run `./bootstrap.sh` from the repo root). Then, from the repo root:

```bash
source proxmox/.env
ansible-playbook playbooks/deploy-host.yaml -e network=home -e host=gitea
```

`proxmox/.env` provides the Proxmox token and the deployment SSH key. The playbook reads `secrets/home/gitea.env` itself.

On a first run the playbook:

1. Clones the template into VM 114, adds the data disk (scsi1) and starts the VM. The clone boots on the template's IP, `192.168.1.10`.
2. Formats the data disk as ext4.
3. Installs the NixOS configuration into `/etc/nixos`: `common.nix`, plus `network.nix` and `gitea.nix` generated from `vars.yaml`, plus `configuration.nix`.
4. Runs `nixos-rebuild build`, so any error shows up before anything changes, then `nixos-rebuild switch`. The VM moves to its own IP. For the isolated network, the playbook also moves the VM's network card to `vmbr1` and reconnects through the router.
5. Checks that the data disk is mounted at `/var/lib/gitea` and that Gitea is running.
6. Creates the admin user from `.env`.
7. Checks that Gitea answers, from your machine or, on the isolated network, from the router. Then prints the address.

Because new clones use the template's IP, deploy one VM at a time.

## Using Gitea

Open `http://192.168.1.14:3000/` and log in as the admin. Add users under Site Administration, or set `gitea_allow_registration: true` to let people sign up themselves.

To push over SSH, add your public key under Settings → SSH / GPG Keys, then:

```bash
git clone gitea@192.168.1.14:<owner>/<repo>.git
```

Git over SSH uses the VM's normal SSH server on port 22, logging in as the `gitea` user. Your key only lets you run Git commands, not open a shell.

## Home or isolated network

`gitea_network` in `vars.yaml` decides where the VM lives:

- `home` (the default): on `vmbr0` at `192.168.1.14`.
- `isolated`: on the router's isolated LAN at `10.1.0.14` (`gitea_isolated_ip`). It reaches the internet through the router, but not the home network. Deploy the router first.

To deploy straight onto the isolated network, set `gitea_network: "isolated"` before the first run. To move a deployed server, change the setting and re-run `gitea.yaml`, or move it without redeploying:

```bash
# move the host's entry to the other network file, then deploy it
# move the host's entry to the other network file, then deploy it
```

`move-network.yaml` only changes the network settings and keeps the data disk as it is. It doesn't update the address Gitea shows in links and clone URLs, so re-run `gitea.yaml` afterwards.

### Behind the network's proxy

Give Gitea a [proxy route](../proxy/README.md) to its web port:

```yaml
    proxy:
      - name: git
        port: 3000
        # external: true     # also reachable from home, through the router
```

Gitea then uses `https://git.lab.home.arpa/` as its address in links and redirects, requires HTTPS for its login cookie, and trusts the proxy's forwarded client addresses. SSH clone URLs use the VM's own name, such as `gitea.lab.home.arpa`, because the route's name points at the proxy, which only serves HTTPS. Set `public_host` and `public_ssh_port` to change the SSH address. With a route, they no longer change the web address.

### Reaching Gitea on the isolated network from home

[Expose](../router/README.md#port-forwards) the web interface and SSH in the host's entry. TCP 22 on the router is its own SSH, so use another router port for the VM's 22:

```yaml
    expose:
      - name: web
        port: 3000
      - name: ssh
        port: 22
        wan_port: 2222
```

Redeploy the router. Then tell Gitea the address people use, so its links and clone URLs point at the router, and redeploy Gitea:

```yaml
    settings:
      public_host: "192.168.1.13"
      public_http_port: 3000
      public_ssh_port: 2222
```

Gitea is then at `http://192.168.1.13:3000/`, and clones over SSH use `ssh://gitea@192.168.1.13:2222/<owner>/<repo>.git`.

## Data disk

Repositories, LFS files, attachments, the SQLite database, Gitea's settings and the `gitea` user's SSH keys are all on their own disk (scsi1, serial `gitea-data`), separate from the operating system. The size is `gitea_data_disk_gb` in `vars.yaml`.

- **Growing:** raise `gitea_data_disk_gb` and re-run the playbook. It grows the disk in Proxmox, then grows the filesystem while Gitea keeps running.
- **Shrinking isn't possible.** Proxmox can't shrink disks, so the playbook stops with an error if the value is smaller than the current disk.
- **Re-runs never wipe it.** The disk is only formatted if it has no filesystem yet.

If the disk is ever missing at boot, the VM still starts and you can SSH in, but Gitea won't start. That stops it from starting over with an empty setup on the system disk.

## Making changes

Edit the files here and re-run the playbook. When VM 114 already exists, the playbook updates it in place on its own IP and doesn't re-clone it.

- **Web port, public address or sign-up:** change them in `vars.yaml`. The firewall follows the web port.
- **Other Gitea settings:** add them under `services.gitea.settings` in `configuration.nix`. Leave the hostname, IP, ports and sign-up out of it; they belong in `vars.yaml`.

The playbook refuses to configure VM 114 if it exists under a name other than `gitea`.

## Linked clone

By default the VM is a linked clone (`gitea_full_clone: false`). It's created quickly and uses little disk, but Proxmox won't delete the template while the clone exists, so `./bootstrap.sh --force` fails. Set `gitea_full_clone: true` before the first deploy to make an independent copy instead. The data disk is always a separate, independent disk.

## Removing the server

```bash
source proxmox/.env
ansible-playbook playbooks/destroy-host.yaml -e network=home -e host=gitea
```

This permanently deletes VM 114, its data disk and every repository on it. The playbook asks you to type `gitea` to confirm. To skip the prompt in a script, pass `-e confirm_destroy=gitea`.

It then stops the VM, deletes it, and removes `192.168.1.14` and `10.1.0.14` from your known_hosts. It refuses to delete VM 114 if that VM has a name other than `gitea`, and does nothing if the VM doesn't exist.
