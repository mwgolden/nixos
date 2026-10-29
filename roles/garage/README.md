# Garage

> **Moved to network files.** This host is now set up from its entry in [networks/home.yaml](../../networks/home.yaml), and deployed with `playbooks/deploy-host.yaml -e network=home -e host=garage`. Secrets are in `secrets/home/garage.env` (see [secrets/README.md](../../secrets/README.md)). The commands below have been updated. Where the text still names an old `vars.yaml` setting, this table shows where that setting is now:
>
> | Old setting | In the network file |
> |---|---|
> | `garage_vm_id` | `vm_id` |
> | `garage_vm_name` | `name` |
> | `garage_full_clone` | `full_clone` |
> | `garage_ip / garage_isolated_ip` | ip, in whichever network file the host is in |
> | `garage_network` | which network file the host is in |
> | `garage_data_disk_gb` | `data_disk.size_gb` |
> | `garage_data_disk_storage` | `data_disk.storage` |
> | `garage_s3_port` | `settings.s3_port` |
> | `garage_s3_region` | `settings.s3_region` |
> | `garage_zone` | `settings.zone` |
> | `garage_key_name` | `settings.key_name` |
> | `garage_buckets` | `settings.buckets` |


A NixOS VM running [Garage](https://garagehq.deuxfleurs.fr/), S3-compatible object storage. Everything Garage stores is on a separate data disk.

Garage replaces MinIO here. MinIO's open-source edition is abandoned upstream, and nixpkgs marks it insecure because of unfixed security bugs, including ones that let anyone write objects without a key.

| Setting    | Value                                         |
| ---------- | --------------------------------------------- |
| VM         | 115, `garage`                                 |
| Network    | `home` (`vmbr0`), or `isolated` behind the [router](../router/README.md) |
| IP         | `192.168.1.15` on the home network, `10.1.0.15` on the isolated network |
| S3 API     | `http://<IP>:3900`, region `garage`           |
| Data disk  | 128 GB, mounted at `/var/lib/garage`          |
| Version    | Garage 2 (`pkgs.garage_2`), single node, one copy of each object |

These values come from `vars.yaml`. Garage has no web console; manage it with S3 tools or the `garage` command on the VM.

## Files

| File                | Purpose                                                                 |
| ------------------- | ----------------------------------------------------------------------- |
| `vars.yaml`         | VM ID, IPs, network, data disk size, S3 port and region, buckets        |
| `.env`              | S3 access key ID and secret (gitignored)                                |
| `.env.example`      | Template for `.env`, with commands to generate a key                    |
| `configuration.nix` | NixOS configuration: Garage service and the data disk mount             |
| `garage.nix.j2`     | Template for the generated settings: S3 port, region, firewall          |
| `garage.yaml`       | Deploy playbook                                                         |
| `destroy.yaml`      | Deletes the VM and its data disk                                        |

Shared settings (Proxmox host, node, template, gateway, DNS) come from `proxmox/vars.yaml`. The hostname and IP file is generated from `modules/network.nix.j2`.

## Access key

The S3 access key is in `secrets/home/garage.env`:

```bash
GARAGE_ACCESS_KEY_ID=GK...
GARAGE_SECRET_ACCESS_KEY=...
```

If `.env` doesn't exist, copy `.env.example` to `.env` and generate a key pair:

```bash
echo "GARAGE_ACCESS_KEY_ID=GK$(openssl rand -hex 12)"
echo "GARAGE_SECRET_ACCESS_KEY=$(openssl rand -hex 32)"
```

Garage requires this format: `GK` and 24 hex digits for the ID, 64 hex digits for the secret.

The playbook imports this key into Garage on the first run, lets it create buckets, and gives it read, write and owner rights on every bucket in `garage_buckets`. The secret is kept out of Ansible's output and the NixOS configuration.

Garage can't change a key's secret. If you change the secret in `.env` later, the playbook stops and tells you how to delete the old key so it can import the new one. Deleting a key also removes its rights on buckets; re-running the playbook gives them back for `garage_buckets`.

## Deploying

The NixOS template must exist first (run `./bootstrap.sh` from the repo root). Then, from the repo root:

```bash
source proxmox/.env
ansible-playbook playbooks/deploy-host.yaml -e network=home -e host=garage
```

`proxmox/.env` provides the Proxmox token and the deployment SSH key. The playbook reads `secrets/home/garage.env` itself.

On a first run the playbook:

1. Clones the template into VM 115, adds the data disk (scsi1) and starts the VM. The clone boots on the template's IP, `192.168.1.10`.
2. Formats the data disk as ext4.
3. Installs the NixOS configuration into `/etc/nixos`: `common.nix`, plus `network.nix` and `garage.nix` generated from `vars.yaml`, plus `configuration.nix`.
4. Runs `nixos-rebuild build`, so any error shows up before anything changes, then `nixos-rebuild switch`. The VM moves to its own IP. For the isolated network, the playbook also moves the VM's network card to `vmbr1` and reconnects through the router.
5. Checks that the data disk is mounted at `/var/lib/garage`.
6. Gives the node its storage role in Garage's cluster layout, sized to the data disk, and waits for Garage to report healthy. Garage stores nothing until this is done.
7. Imports the access key from `.env` and creates the buckets in `garage_buckets`.
8. Checks that the S3 API answers, from your machine or, on the isolated network, from the router. Then prints the endpoint.

Because new clones use the template's IP, deploy one VM at a time.

## Using Garage

Any S3 client works. Use endpoint `http://192.168.1.15:3900`, region `garage`, and path-style addressing (Garage doesn't do bucket names in the host name here). With the AWS CLI:

```bash
export AWS_ACCESS_KEY_ID=GK...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=garage
export AWS_ENDPOINT_URL=http://192.168.1.15:3900

aws s3 mb s3://backups
aws s3 cp ./file.txt s3://backups/
aws s3 ls s3://backups/
```

Buckets you create this way belong to the key from `.env`. To have the playbook create them, list them in `garage_buckets` in `vars.yaml` and re-run.

Traffic is plain HTTP, so keep Garage on a network you trust, or put it on the isolated network.

### The `garage` command

For anything else (more keys, quotas, bucket aliases, status), SSH to the VM and use `garage` as root:

```bash
ssh admin@192.168.1.15
sudo garage status
sudo garage bucket list
sudo garage key create other-app
sudo garage bucket allow --read --write backups --key other-app
```

## Home or isolated network

`garage_network` in `vars.yaml` decides where the VM lives:

- `home` (the default): on `vmbr0` at `192.168.1.15`.
- `isolated`: on the router's isolated LAN at `10.1.0.15` (`garage_isolated_ip`). It reaches the internet through the router, but not the home network. Deploy the router first.

To deploy straight onto the isolated network, set `garage_network: "isolated"` before the first run. To move a deployed server, change the setting and re-run `garage.yaml`, or move it without redeploying:

```bash
# move the host's entry to the other network file, then deploy it
# move the host's entry to the other network file, then deploy it
```

`move-network.yaml` only changes the network settings and keeps the data disk as it is. Garage itself doesn't need to know its address, so nothing else changes.

### Reaching Garage on the isolated network from home

Add a [router port forward](../router/README.md#port-forwards) for the S3 API:

```yaml
router_port_forwards:
  - name: garage-s3
    proto: tcp
    wan_port: 3900
    lan_ip: "10.1.0.15"
```

Run `the router's deploy`. S3 clients then use `http://192.168.1.13:3900`.

## Data disk

Objects, Garage's metadata database (with a snapshot every 6 hours in `meta/snapshots`) and the RPC secret are all on their own disk (scsi1, serial `garage-data`), separate from the operating system. The size is `garage_data_disk_gb` in `vars.yaml`.

- **Growing:** raise `garage_data_disk_gb` and re-run the playbook. It grows the disk in Proxmox, grows the filesystem while Garage keeps running, and updates the node's capacity in Garage's layout.
- **Shrinking isn't possible.** Proxmox can't shrink disks, so the playbook stops with an error if the value is smaller than the current disk.
- **Re-runs never wipe it.** The disk is only formatted if it has no filesystem yet.

If the disk is ever missing at boot, the VM still starts and you can SSH in, but Garage won't start. That stops it from starting over with an empty store on the system disk.

## Making changes

Edit the files here and re-run the playbook. When VM 115 already exists, the playbook updates it in place on its own IP and doesn't re-clone it.

- **S3 port, region, buckets, key name:** change them in `vars.yaml`. The firewall follows the port. Removing a bucket from `garage_buckets` doesn't delete it.
- **Other Garage settings:** add them under `services.garage.settings` in `configuration.nix`. Leave the S3 port and region out of it; they belong in `vars.yaml`.
- **Upgrading Garage:** Garage can only move up one major version at a time and needs migration steps. Read the Garage section of the NixOS manual before changing `services.garage.package`.

The playbook refuses to configure VM 115 if it exists under a name other than `garage`.

## Linked clone

By default the VM is a linked clone (`garage_full_clone: false`). It's created quickly and uses little disk, but Proxmox won't delete the template while the clone exists, so `./bootstrap.sh --force` fails. Set `garage_full_clone: true` before the first deploy to make an independent copy instead. The data disk is always a separate, independent disk.

## Removing the server

```bash
source proxmox/.env
ansible-playbook playbooks/destroy-host.yaml -e network=home -e host=garage
```

This permanently deletes VM 115, its data disk and every object stored on it. The playbook asks you to type `garage` to confirm. To skip the prompt in a script, pass `-e confirm_destroy=garage`.

It then stops the VM, deletes it, and removes `192.168.1.15` and `10.1.0.15` from your known_hosts. It refuses to delete VM 115 if that VM has a name other than `garage`, and does nothing if the VM doesn't exist.
