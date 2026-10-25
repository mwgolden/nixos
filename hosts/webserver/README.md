# Webserver

A NixOS VM running nginx, serving the static files in `site/`.

| Setting  | Value          |
| -------- | -------------- |
| VM       | 111, `webserver` |
| IP       | `192.168.1.11` |
| Serves   | `http://192.168.1.11/` from `/var/www` |

These values come from `vars.yaml`.

## Files

| File                | Purpose                                                            |
| ------------------- | ------------------------------------------------------------------ |
| `vars.yaml`         | VM ID, name, IP and clone type                                     |
| `configuration.nix` | NixOS configuration: nginx, firewall, `/var/www`                   |
| `site/`             | Files copied to `/var/www` and served by nginx                     |
| `webserver.yaml`    | Deploy playbook                                                    |
| `destroy.yaml`      | Deletes the webserver VM                                           |

Shared settings (Proxmox host, node, template, gateway, DNS) come from `proxmox/vars.yaml`.

## Deploying

The NixOS template must exist first (run `./bootstrap.sh` from the repo root). Then, from the repo root:

```bash
source proxmox/.env
ansible-playbook hosts/webserver/webserver.yaml
```

Unlike `bootstrap.sh`, the playbook doesn't load `proxmox/.env` itself, so source it first. It needs `PROXMOX_TOKEN_SECRET` and the deployment key pair (`NIXOS_DEPLOYMENT_PUBLIC_KEY`, `NIXOS_DEPLOYMENT_PRIVATE_KEY`), and stops with a clear message if one is missing. Without the secret, Proxmox answers `401 Unauthorized: invalid token value`.

On a first run the playbook:

1. Clones the template into VM 111 and starts it. The clone boots on the template's IP, `192.168.1.10`.
2. Installs `common.nix`, a generated `network.nix` (hostname and IP from `vars.yaml`) and `configuration.nix` into `/etc/nixos`.
3. Copies `site/` to `/var/www`.
4. Runs `nixos-rebuild build`, so any error shows up before anything changes.
5. Runs `nixos-rebuild switch`. The VM moves to `192.168.1.11` and the SSH connection drops, so this runs in the background.
6. Waits for SSH on the new IP, then checks that `http://192.168.1.11/` returns 200.

Because new clones use the template's IP, deploy one VM at a time.

## Making changes

Edit the files here and re-run the playbook. When VM 111 already exists, the playbook updates it in place on its own IP. It doesn't re-clone, and it runs the switch in the foreground.

- **Site content:** add or edit files in `site/`. Files deleted from `site/` are not removed from the server.
- **NixOS settings:** edit `configuration.nix`. Leave the hostname and IP out of it; they belong in `vars.yaml`.
- **IP address:** change `webserver_ip` in `vars.yaml`. After the switch, the playbook looks for the server on the new address.

The playbook refuses to configure VM 111 if it exists under a name other than `webserver`.

## Linked clone

By default the VM is a linked clone (`webserver_full_clone: false`). It's created quickly and uses little disk, but Proxmox won't delete the template while the clone exists, so `./bootstrap.sh --force` fails. Set `webserver_full_clone: true` before the first deploy to make an independent copy instead.

## Removing the webserver

```bash
source proxmox/.env
ansible-playbook hosts/webserver/destroy.yaml
```

This permanently deletes VM 111 and its disk, including anything in `/var/www` that isn't in `site/`. The playbook asks you to type `webserver` to confirm. To skip the prompt in a script, pass `-e confirm_destroy=webserver`.

It then stops the VM, deletes it, and removes `192.168.1.11` from your known_hosts. It refuses to delete VM 111 if that VM has a name other than `webserver`, and does nothing if the VM doesn't exist.

Once the webserver is gone, `./bootstrap.sh --force` can delete the template again.
