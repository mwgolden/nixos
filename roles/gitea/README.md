# Gitea

A NixOS VM running [Gitea](https://about.gitea.com/), a self-hosted Git server with a web interface. Everything Gitea keeps, including its SQLite database, is on a separate data disk.

```yaml
hosts:
  - name: gitea
    type: gitea
    vm_id: 114
    ip: 10.1.0.14
    data_disk:
      size_gb: 40          # mounted at /var/lib/gitea
      storage: local-lvm
    settings:
      # All optional; these are the defaults.
      http_port: 3000
      allow_registration: false   # only the admin can add users
      # Overrides for the address in links and clone URLs; see below.
      public_host: ""
      public_http_port: ""
      public_ssh_port: ""
```

The web interface is on `http_port`. Git works over HTTP, or over SSH as `gitea@<host>` on the VM's normal SSH port, 22.

## Admin login

Copy [env.example](env.example) to `secrets/<network>/<host>.env`, such as `secrets/lab/gitea.env`:

```bash
GITEA_ADMIN_USER=gitadmin
GITEA_ADMIN_PASSWORD=...
GITEA_ADMIN_EMAIL=gitadmin@example.com
```

The user name can't be `admin`, which Gitea reserves, and the password needs at least 8 characters. The deploy creates this user on the first run and sets its password on every run, so to change it, edit the file and redeploy. Changing the email later doesn't change it in Gitea; do that in the web interface.

## Deploying

```bash
source proxmox/.env
ansible-playbook playbooks/deploy-host.yaml -e network=lab -e host=gitea
```

Besides the steps every host goes through, the deploy adds and formats the data disk (scsi1, serial `gitea-data`) if it has no filesystem yet, checks Gitea is running, creates or updates the admin user, and checks `/api/healthz` answers. It ends by printing Gitea's address and SSH clone URL.

## Using Gitea

Open the web address and log in as the admin. Add users under Site Administration, or set `allow_registration: true` to let people sign up.

To push over SSH, add your public key under Settings → SSH / GPG Keys, then clone with the URL the repository page shows, such as:

```bash
git clone gitea@192.168.1.14:<owner>/<repo>.git
```

Your key only lets you run Git commands as the `gitea` user, not open a shell.

## Its address

Gitea puts its own address in links, redirects and clone URLs, so it has to know the address people use. The deploy works it out from the host's entry:

| Host entry | Web address | SSH clones |
|---|---|---|
| Home network | `http://192.168.1.14:3000/` | `192.168.1.14`, port 22 |
| Isolated, nothing else | `http://10.1.0.14:3000/`, from the network's VMs and VPN | `10.1.0.14`, port 22 |
| `proxy:` route to `http_port` | `https://git.lab.home.arpa/` | `gitea.lab.home.arpa`, port 22 |
| `expose:` entry for `http_port` | `http://192.168.1.13:<wan_port>/` | |
| `expose:` entry for port 22 | | `192.168.1.13`, its `wan_port` |

A route wins over an `expose:` entry for the web address. Behind a route, SSH uses the VM's own name: the route's name points at the proxy, which only serves HTTPS.

Set `public_host`, `public_http_port` or `public_ssh_port` only to override this, such as for a name you gave the router's address on the home router. `public_host` sets the host for both web and SSH; with a route, `public_http_port` is ignored.

### Reaching it from home

From an isolated network, either publish the web interface through the [proxy](../proxy/README.md):

```yaml
    proxy:
      - name: git
        port: 3000
        external: true
```

or forward the ports. TCP 22 on the router is its own SSH, so use another router port for the VM's 22:

```yaml
    expose:
      - name: web
        port: 3000
      - name: ssh
        port: 22
        wan_port: 2222
```

You can combine the two: a route for the web interface, plus the `ssh` forward. Then redeploy the router and Gitea (`deploy-network` does both). With the forwards above, Gitea is at `http://192.168.1.13:3000/` and clones use `ssh://gitea@192.168.1.13:2222/<owner>/<repo>.git`.

Forwarded addresses only work from home. VMs inside the network can't reach the router's WAN address, so they clone from `gitea.lab.home.arpa` instead.

### Behind the proxy

With a route, Gitea also requires HTTPS for its login cookie, and trusts the client addresses the proxy passes on. Direct `http://` access on port 3000 still works inside the network, but logins need HTTPS.

## Data disk

Repositories, LFS files, attachments, the SQLite database, Gitea's settings and the `gitea` user's SSH keys are all on the data disk.

- **Growing:** raise `data_disk.size_gb` and redeploy. The filesystem grows while Gitea keeps running.
- **Shrinking isn't possible.** The deploy stops if the size is smaller than the current disk.
- **Redeploys never wipe it.** It is only formatted if it has no filesystem yet.

If the disk is missing at boot, the VM still starts, but Gitea doesn't. That stops it starting over with an empty setup on the system disk.

## Making changes

Edit the host's entry or the files here and redeploy. An existing VM is updated in place.

- **Web port, address or sign-up:** change them under `settings:`, or change `proxy:` and `expose:`. The firewall follows the web port.
- **Other Gitea settings:** add them under `services.gitea.settings` in [files/configuration.nix](files/configuration.nix). Leave the hostname, addresses, ports and sign-up out; they come from the network file.
- **Address or network:** change `ip`, or move the entry to another network file, and redeploy. The data disk moves with the VM, and the deploy updates the address in links. See [Moving a VM between networks](../../README.md#moving-a-vm-between-networks).

## Files

| File | Purpose |
|---|---|
| `files/configuration.nix` | NixOS configuration: Gitea and the data disk mount |
| `templates/gitea.nix.j2` | Generated settings: addresses, ports, sign-up, proxy, firewall |
| `defaults/main.yml` | Settings and how the address is worked out |
| `env.example` | Template for the admin secrets file |
| `tasks/` | `prepare.yml` (secrets), `configure.yml` (disk, switch, admin), `verify.yml`, `ports.yml` |

## Removing it

```bash
ansible-playbook playbooks/destroy-host.yaml -e network=lab -e host=gitea
```

This permanently deletes the VM, its data disk and every repository on it. It asks you to type the host name. Remove the entry from the network file too, or the next deploy creates it again.
