# Webserver

> **Moved to network files.** This host is now set up from its entry in [networks/home.yaml](../../networks/home.yaml), and deployed with `playbooks/deploy-host.yaml -e network=home -e host=webserver`. Secrets are in `secrets/home/webserver.env` (see [secrets/README.md](../../secrets/README.md)). The commands below have been updated. Where the text still names an old `vars.yaml` setting, this table shows where that setting is now:
>
> | Old setting | In the network file |
> |---|---|
> | `webserver_vm_id` | `vm_id` |
> | `webserver_vm_name` | `name` |
> | `webserver_full_clone` | `full_clone` |
> | `webserver_ip / webserver_isolated_ip` | ip, in whichever network file the host is in |
> | `webserver_network` | which network file the host is in |


A NixOS VM running nginx, serving the static files in `site/`.

| Setting  | Value          |
| -------- | -------------- |
| VM       | 111, `webserver` |
| Network  | `home` (`vmbr0`), or `isolated` behind the [router](../router/README.md) |
| IP       | `192.168.1.11` on the home network, `10.1.0.11` on the isolated network |
| Serves   | `http://<IP>/` from `/var/www` |

These values come from `vars.yaml`.

## Files

| File                | Purpose                                                            |
| ------------------- | ------------------------------------------------------------------ |
| `vars.yaml`         | VM ID, name, network, IPs and clone type                           |
| `configuration.nix` | NixOS configuration: nginx, firewall, `/var/www`                   |
| `site/`             | Files copied to `/var/www` and served by nginx                     |
| `webserver.yaml`    | Deploy playbook                                                    |
| `destroy.yaml`      | Deletes the webserver VM                                           |

Shared settings (Proxmox host, node, template, gateway, DNS) come from `proxmox/vars.yaml`.

## Deploying

The NixOS template must exist first (run `./bootstrap.sh` from the repo root). Then, from the repo root:

```bash
source proxmox/.env
ansible-playbook playbooks/deploy-host.yaml -e network=home -e host=webserver
```

Unlike `bootstrap.sh`, the playbook doesn't load `proxmox/.env` itself, so source it first. It needs `PROXMOX_TOKEN_SECRET` and the deployment key pair (`NIXOS_DEPLOYMENT_PUBLIC_KEY`, `NIXOS_DEPLOYMENT_PRIVATE_KEY`), and stops with a clear message if one is missing. Without the secret, Proxmox answers `401 Unauthorized: invalid token value`.

On a first run the playbook:

1. Clones the template into VM 111 and starts it. The clone boots on the template's IP, `192.168.1.10`, on the home network.
2. Installs `common.nix`, a generated `network.nix` (hostname, IP, gateway and DNS for the chosen network) and `configuration.nix` into `/etc/nixos`.
3. Copies `site/` to `/var/www`.
4. Runs `nixos-rebuild build`, so any error shows up before anything changes.
5. Runs `nixos-rebuild switch`. The VM moves to its own IP and the SSH connection drops, so this runs in the background. For the isolated network, the playbook also moves the VM's network card to `vmbr1`.
6. Waits for SSH on the new IP and for the switch to finish, then checks that the site returns 200. On the isolated network, that check runs on the router.

Because new clones use the template's IP, deploy one VM at a time.

## Home or isolated network

`webserver_network` in `vars.yaml` decides where the VM lives:

- `home`: on `vmbr0` at `192.168.1.11`, like the other VMs.
- `isolated`: on the router's isolated LAN at `10.1.0.11` (`webserver_isolated_ip`). It reaches the internet through the router, but not the home network. From home, the site is only reachable through a [router port forward](../router/README.md#port-forwards). Deploy the router first.

To deploy straight onto the isolated network, set `webserver_network: "isolated"` before the first run. The clone still starts on the home network, because the template's address is there. The playbook then switches it over.

To move a deployed webserver, either change `webserver_network` and re-run `webserver.yaml`, or move it without redeploying:

```bash
# move the host's entry to the other network file, then deploy it
# move the host's entry to the other network file, then deploy it
```

`move-network.yaml` only changes the VM's network settings, and updates `webserver_network` in `vars.yaml` to match. See the [main README](../../README.md#moving-a-vm-between-networks).

To publish the site from the isolated network, [expose](../router/README.md#port-forwards) port 80 in the host's entry and redeploy the router:

```yaml
    expose:
      - port: 80
```

The site is then at `http://192.168.1.13/`.

## Making changes

Edit the files here and re-run the playbook. When VM 111 already exists, the playbook updates it in place on its own IP. It doesn't re-clone, and it runs the switch in the foreground.

- **Site content:** add or edit files in `site/`. Files deleted from `site/` are not removed from the server.
- **NixOS settings:** edit `configuration.nix`. Leave the hostname and IP out of it; they belong in `vars.yaml`.
- **IP address:** change `webserver_ip` (home) or `webserver_isolated_ip` in `vars.yaml`. After the switch, the playbook looks for the server on the new address. Keep the isolated address outside the router's DHCP range (`10.1.0.100`–`199`).

The playbook refuses to configure VM 111 if it exists under a name other than `webserver`.

## Linked clone

By default the VM is a linked clone (`webserver_full_clone: false`). It's created quickly and uses little disk, but Proxmox won't delete the template while the clone exists, so `./bootstrap.sh --force` fails. Set `webserver_full_clone: true` before the first deploy to make an independent copy instead.

## Removing the webserver

```bash
source proxmox/.env
ansible-playbook playbooks/destroy-host.yaml -e network=home -e host=webserver
```

This permanently deletes VM 111 and its disk, including anything in `/var/www` that isn't in `site/`. The playbook asks you to type `webserver` to confirm. To skip the prompt in a script, pass `-e confirm_destroy=webserver`.

It then stops the VM, deletes it, and removes `192.168.1.11` and `10.1.0.11` from your known_hosts. It refuses to delete VM 111 if that VM has a name other than `webserver`, and does nothing if the VM doesn't exist.

Once the webserver is gone, `./bootstrap.sh --force` can delete the template again.
