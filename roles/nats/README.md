# NATS

A NixOS VM running [NATS](https://nats.io/) (`pkgs.nats-server`), a messaging server, with [JetStream](https://docs.nats.io/nats-concepts/jetstream) turned on for streams, key-value buckets and object stores that persist. It runs as a single server. JetStream's data is on a separate data disk.

```yaml
hosts:
  - name: nats
    type: nats
    vm_id: 118
    ip: 10.1.0.18
    data_disk:
      size_gb: 20          # mounted at /var/lib/nats
      storage: local-lvm
    settings:
      # All optional; these are the defaults.
      port: 4222
      jetstream:
        max_memory: 256M   # for streams kept in memory
        max_file: ""       # for streams on disk; empty is 90% of the data disk
```

Sizes are a number followed by `K`, `M`, `G` or `T`. The defaults are in [defaults/main.yml](defaults/main.yml).

## Client login

Copy [env.example](env.example) to `secrets/<network>/<host>.env`, such as `secrets/lab/nats.env`, and set a password:

```bash
NATS_USER=app
NATS_PASSWORD=...          # openssl rand -base64 32
```

Every client logs in with this user, which can publish and subscribe to any subject and use JetStream. The user name may contain letters, digits, `_` and `-`. The password needs at least 16 characters from letters, digits and `. _ ~ + / = -`, which covers anything `openssl rand -base64` makes.

The login is written to `/etc/nats/nats.env` on the VM, readable only by root, and systemd passes it to the server as environment variables. It stays out of Ansible's output and out of the Nix store. To change it, edit the file and redeploy; NATS restarts with the new login, and connected clients have to reconnect.

## Deploying

```bash
source proxmox/.env
ansible-playbook playbooks/deploy-host.yaml -e network=lab -e host=nats
```

Besides the steps every host goes through, the deploy:

1. Adds the data disk (scsi1, serial `nats-data`) and formats it as ext4 if it has no filesystem yet, then checks it is mounted.
2. Installs the client login, and the NATS configuration, which is checked with `nats-server -t` when NixOS builds it.
3. Waits for NATS to report healthy with JetStream on, through its monitoring endpoint on `127.0.0.1:8222`.
4. Checks the client port answers (from the router, on an isolated network) and prints how to connect.

## Quickstart

A walk-through with the [nats CLI](https://github.com/nats-io/natscli), for a host on the home network:

```yaml
# networks/home.yaml
hosts:
  - name: nats
    type: nats
    vm_id: 118
    ip: 192.168.1.18
    data_disk:
      size_gb: 20
      storage: local-lvm
```

Hosts on a home network are reached directly by address, so the server is `nats://192.168.1.18:4222`. On an isolated network, use the host's name or the router's forwarded port instead; see [On an isolated network](#on-an-isolated-network). Run these from the repo root once the host is deployed.

### 1. Save a context

```bash
source secrets/home/nats.env

nats context save home \
  --server nats://192.168.1.18:4222 \
  --user "$NATS_USER" \
  --password "$NATS_PASSWORD" \
  --description "NATS on the home network"

nats context select home
```

The context stores the password in plain text under `~/.config/nats/context/home.json`.

### 2. Check the connection

```bash
nats rtt            # round-trip time to the server
nats account info   # shows JetStream is enabled, and its memory and disk limits
```

With the defaults, `account info` shows a memory limit of 256 MiB, and a disk limit of about 18 GiB (90% of the 20 GB disk).

### 3. Publish and subscribe

In one terminal:

```bash
nats sub 'greet.>'
```

In another:

```bash
nats pub greet.home "hello from the home network"
```

The subscriber prints the message. Plain messages aren't stored, so a subscriber that starts later won't see it.

### 4. A stream, stored on the data disk

```bash
# Keep every message on subjects under orders. on disk
nats stream add ORDERS --subjects 'orders.>' --storage file --defaults

nats pub orders.new '{"id": 1, "item": "widget"}'
nats pub orders.new '{"id": 2, "item": "gadget"}'

nats stream info ORDERS        # message count and bytes used
nats stream view ORDERS        # read the stored messages

# A pull consumer that workers read from, picking up where they left off
nats consumer add ORDERS worker --pull --defaults
nats consumer next ORDERS worker --count 2
```

### 5. A key-value bucket

```bash
nats kv add config
nats kv put config mode on
nats kv get config mode
nats kv watch config           # in another terminal, then run another put
```

### 6. An object store

```bash
nats object add files
nats object put files ./report.pdf
nats object ls files
nats object get files report.pdf --output /tmp/report.pdf
```

### Cleaning up

```bash
nats stream rm ORDERS -f
nats kv del config -f
nats object del files -f
```

## Using NATS

Client libraries take the same URL, user and password as the CLI.

Traffic isn't encrypted, so keep NATS on a network you trust, or on an isolated one. The password is the only thing keeping other machines on those networks out.

### Monitoring

The monitoring endpoint listens on the VM's loopback only. To look at it from your machine, forward it over SSH:

```bash
ssh -L 8222:127.0.0.1:8222 admin@<nats address>
curl http://127.0.0.1:8222/varz
curl http://127.0.0.1:8222/jsz
```

## On an isolated network

The network's VMs and VPN clients use `nats://nats.lab.home.arpa:4222`. To reach it from home, forward the client port in the host's entry and redeploy the router:

```yaml
    expose:
      - port: 4222
```

Clients at home then use `nats://192.168.1.13:4222`.

## Data disk

JetStream keeps streams, key-value buckets and object stores in `/var/lib/nats/jetstream` on the data disk. Plain publish and subscribe messages aren't stored at all.

- **Growing:** raise `data_disk.size_gb` and redeploy. The filesystem grows while NATS keeps running. Unless `jetstream.max_file` is set, JetStream's limit grows with it.
- **Shrinking isn't possible.** The deploy stops if the size is smaller than the current disk.
- **Redeploys never wipe it.** It is only formatted if it has no filesystem yet.

If the disk is missing at boot, the VM still starts, but NATS doesn't. That stops it starting over with empty streams on the system disk.

## Making changes

Edit the host's entry or the files here and redeploy. An existing VM is updated in place.

- **Port or JetStream limits:** change them under `settings:`. The firewall follows the port. If the host is exposed, change its `expose:` port to match.
- **Other NATS settings:** add them to the configuration text in [templates/nats.nix.j2](templates/nats.nix.j2), such as `max_payload` or more users with their own permissions. NixOS checks the file when it builds, so a mistake stops the deploy before NATS restarts.
- **Address or network:** change `ip`, or move the entry to another network file, and redeploy. See [Moving a VM between networks](../../README.md#moving-a-vm-between-networks).

## Files

| File | Purpose |
|---|---|
| `files/configuration.nix` | NixOS configuration: the NATS service, its login file and the data disk mount |
| `templates/nats.nix.j2` | Generated NATS configuration: port, JetStream limits, login, firewall |
| `env.example` | Template for the client login's secrets file |
| `tasks/` | `prepare.yml` (secrets, settings), `configure.yml` (disk, login, switch, health), `verify.yml`, `ports.yml` |

## Removing it

```bash
ansible-playbook playbooks/destroy-host.yaml -e network=lab -e host=nats
```

This permanently deletes the VM, its data disk and every stream on it. It asks you to type the host name. Remove the entry from the network file too, or the next deploy creates it again.
