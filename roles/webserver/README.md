# Webserver

A NixOS VM running nginx, serving the static files in [files/site/](files/site/) at `http://<host>/`.

```yaml
hosts:
  - name: webserver
    type: webserver
    vm_id: 150
    ip: 192.168.1.11
```

It has no `settings:` and no secrets. Deploy it like any other host:

```bash
source proxmox/.env
ansible-playbook playbooks/deploy-host.yaml -e network=home -e host=webserver
```

## Files

| File | Purpose |
|---|---|
| `files/configuration.nix` | NixOS configuration: nginx, firewall, `/var/www` |
| `files/site/` | Copied to `/var/www` and served by nginx |
| `tasks/configure.yml` | Installs the configuration and the site, then switches |
| `tasks/verify.yml` | Checks the site returns 200 and says where it is |
| `tasks/ports.yml` | Ports the [network check](../network_verify/README.md) expects it to listen on: 80 |

## On an isolated network

On an isolated network such as `lab`, the site is at `http://<name>.lab.home.arpa/` for the network's VMs and VPN clients. The check after switching runs on the router, since only it can reach the VM.

To reach it from home, either forward the port in the host's entry and redeploy the router:

```yaml
    expose:
      - port: 80
```

The site is then at `http://192.168.1.13/`. Or serve it through the network's [proxy](../proxy/README.md) over HTTPS, with `proxy: [{name: www, port: 80}]`.

## Making changes

Edit the files here and redeploy. An existing VM is updated in place.

- **Site content:** add or edit files in `files/site/`. Files deleted there are not removed from the server.
- **NixOS settings:** edit `files/configuration.nix`. Leave the hostname and addresses out; they come from the network file.
- **Address or network:** change `ip`, or move the entry to another network file, and redeploy. See [Moving a VM between networks](../../README.md#moving-a-vm-between-networks).

## Removing it

```bash
ansible-playbook playbooks/destroy-host.yaml -e network=home -e host=webserver
```

This deletes the VM and its disk, including anything in `/var/www` that isn't in `files/site/`. It asks you to type the host name. Remove the entry from the network file too, or the next deploy creates it again.

A linked clone (the default, `full_clone: false`) stops Proxmox deleting the template while it exists, so `./bootstrap.sh --force` fails until the VM is gone.
