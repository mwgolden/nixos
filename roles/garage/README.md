# Garage

A NixOS VM running [Garage](https://garagehq.deuxfleurs.fr/) 2 (`pkgs.garage_2`), S3-compatible object storage: a single node, keeping one copy of each object. Everything Garage stores is on a separate data disk. Garage has no web console; manage it with S3 tools or the `garage` command on the VM.

Garage replaces MinIO here. MinIO's open-source edition is abandoned upstream, and nixpkgs marks it insecure because of unfixed security bugs, including ones that let anyone write objects without a key.

```yaml
hosts:
  - name: garage
    type: garage
    vm_id: 115
    ip: 192.168.1.15
    data_disk:
      size_gb: 128         # mounted at /var/lib/garage
      storage: local-lvm
    settings:
      # All optional; these are the defaults.
      s3_port: 3900
      s3_region: garage    # the only region Garage accepts
      zone: dc1            # a label, with a single node
      key_name: default    # name of the access key in Garage
      buckets: []          # created if missing; never deleted
```

## Access key

Copy [env.example](env.example) to `secrets/<network>/<host>.env`, such as `secrets/home/garage.env`, and generate a key pair:

```bash
echo "GARAGE_ACCESS_KEY_ID=GK$(openssl rand -hex 12)"
echo "GARAGE_SECRET_ACCESS_KEY=$(openssl rand -hex 32)"
```

Garage requires this format: `GK` and 24 hex digits for the ID, 64 hex digits for the secret.

The deploy imports this key on the first run, lets it create buckets, and gives it read, write and owner rights on every bucket in `settings.buckets`. The secret is kept out of Ansible's output and the NixOS configuration.

Garage can't change a key's secret. If you change it in the secrets file later, the deploy stops and says how to delete the old key so it can import the new one. Deleting a key also removes its rights on buckets; the next deploy gives them back for `settings.buckets`.

## Deploying

```bash
source proxmox/.env
ansible-playbook playbooks/deploy-host.yaml -e network=home -e host=garage
```

Besides the steps every host goes through, the deploy:

1. Adds the data disk (scsi1, serial `garage-data`) and formats it as ext4 if it has no filesystem yet, then checks it is mounted.
2. Gives the node its storage role in Garage's cluster layout, sized to the data disk, and waits for Garage to report healthy. Garage stores nothing until this is done.
3. Imports the access key and creates the buckets.
4. Checks the S3 API answers (from the router, on an isolated network) and prints the endpoint.

## Using Garage

Any S3 client works. Use endpoint `http://<host>:3900`, region `garage`, and path-style addressing (bucket names in the host name aren't set up). With the AWS CLI:

```bash
export AWS_ACCESS_KEY_ID=GK...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=garage
export AWS_ENDPOINT_URL=http://192.168.1.15:3900

aws s3 mb s3://backups
aws s3 cp ./file.txt s3://backups/
aws s3 ls s3://backups/
```

Buckets made this way belong to the key from the secrets file. To have the deploy create them, list them in `settings.buckets`.

Traffic is plain HTTP, so keep Garage on a network you trust, or on an isolated one.

### The `garage` command

For anything else (more keys, quotas, bucket aliases, status), SSH to the VM and use `garage` as root:

```bash
ssh admin@192.168.1.15
sudo garage status
sudo garage bucket list
sudo garage key create other-app
sudo garage bucket allow --read --write backups --key other-app
```

## On an isolated network

The network's VMs and VPN clients use `http://garage.lab.home.arpa:3900`. To reach it from home, forward the S3 port in the host's entry and redeploy the router:

```yaml
    expose:
      - port: 3900
```

S3 clients at home then use `http://192.168.1.13:3900`. Garage doesn't need to know its own address, so moving it between networks changes nothing else.

## Data disk

Objects, Garage's metadata database (with a snapshot every 6 hours in `meta/snapshots`) and the RPC secret are all on the data disk.

- **Growing:** raise `data_disk.size_gb` and redeploy. The filesystem grows while Garage keeps running, and the node's capacity in the layout is updated.
- **Shrinking isn't possible.** The deploy stops if the size is smaller than the current disk.
- **Redeploys never wipe it.** It is only formatted if it has no filesystem yet.

If the disk is missing at boot, the VM still starts, but Garage doesn't. That stops it starting over with an empty store on the system disk.

## Making changes

Edit the host's entry or the files here and redeploy. An existing VM is updated in place.

- **S3 port, region, buckets, key name:** change them under `settings:`. The firewall follows the port. If the host is exposed, change its `expose:` port to match.
- **Other Garage settings:** add them under `services.garage.settings` in [files/configuration.nix](files/configuration.nix). Leave the S3 port and region out; they come from the network file.
- **Upgrading Garage:** Garage moves up one major version at a time, with migration steps. Read the Garage section of the NixOS manual before changing `services.garage.package`.
- **Address or network:** change `ip`, or move the entry to another network file, and redeploy. See [Moving a VM between networks](../../README.md#moving-a-vm-between-networks).

## Files

| File | Purpose |
|---|---|
| `files/configuration.nix` | NixOS configuration: Garage and the data disk mount |
| `templates/garage.nix.j2` | Generated settings: S3 port, region, firewall |
| `env.example` | Template for the access key's secrets file |
| `tasks/` | `prepare.yml` (secrets), `configure.yml` (disk, switch, layout, key, buckets), `verify.yml`, `ports.yml` |

## Removing it

```bash
ansible-playbook playbooks/destroy-host.yaml -e network=home -e host=garage
```

This permanently deletes the VM, its data disk and every object on it. It asks you to type the host name. Remove the entry from the network file too, or the next deploy creates it again.
