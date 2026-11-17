# OpenBao

A NixOS VM running [OpenBao](https://openbao.org/) (`pkgs.openbao`), the open-source fork of HashiCorp Vault, for storing secrets and handing them to other machines. It runs as a single node with integrated (raft) storage on a separate data disk, and serves its API and web UI on one port.

```yaml
hosts:
  - name: openbao
    type: openbao
    vm_id: 120
    ip: 192.168.1.20
    data_disk:
      size_gb: 10          # mounted at /var/lib/openbao
      storage: local-lvm
    settings:
      # All optional; these are the defaults.
      port: 8200
      ui: true             # the web UI at /ui
      key_shares: 1        # unseal keys made on the first deploy
      key_threshold: 1     # how many of them it takes to unseal
      kv_mounts: [secret]  # your own KV version 2 engines; created if missing, never deleted
```

The defaults are in [defaults/main.yml](defaults/main.yml).

Besides `kv_mounts`, every deploy mounts a KV version 2 engine named after the network, such as `lab/`. That is where the deploys of the network's other hosts keep their secrets, one per host at `<network>/<host>`; see [The network's secrets](#the-networks-secrets). `kv_mounts` can't contain the network's name, and a network can have only one openbao host.

## Unseal keys and root token

There's no secrets file to write. On the first deploy, OpenBao is initialized and the deploy writes what that makes to `secrets/<network>/<host>-init.json`, such as `secrets/lab/openbao-init.json`:

- `unseal_keys_b64`: the unseal keys. OpenBao's storage is encrypted, and after every restart it starts **sealed**, unable to read it, until it is given `key_threshold` of these.
- `root_token`: a token that can do anything.

**Back this file up somewhere other than this machine.** Anyone with it can read every secret, and without it a sealed OpenBao can't be opened again: there is no other way in.

The keys are written to a root-only file on the VM first, then copied here and deleted from the VM, so a deploy that fails halfway doesn't lose them. The deploy never overwrites this file. If it finds OpenBao uninitialized while the file exists (a new or wiped data disk), it stops rather than start over; move the file away to accept that.

Each deploy uses the keys to unseal OpenBao if it is sealed, and the root token to mount the network's engine and `kv_mounts`. The deploys of the network's other hosts use the same root token to read and write their secrets, so it can't be revoked; a narrower deploy token is a possible later step.

`key_shares` and `key_threshold` only matter on the first deploy. Splitting the key gains nothing while all the shares are in one file; if you want that, hand them out and remove them from the file, and unseal by hand after a restart (below). Change them later with `bao operator rekey`.

## Deploying

```bash
source proxmox/.env
ansible-playbook playbooks/deploy-host.yaml -e network=lab -e host=openbao
```

Besides the steps every host goes through, the deploy:

1. Adds the data disk (scsi1, serial `openbao-data`) and formats it as ext4 if it has no filesystem yet, then checks it is mounted.
2. Restarts OpenBao if its configuration or package changed. NixOS doesn't do this on a switch, since a restart seals it.
3. Initializes OpenBao on the first deploy and saves the keys, as above.
4. Unseals it if it is sealed, and waits for it to be active.
5. Mounts the network's KV engine (`<network>/`) and those in `kv_mounts` that are missing.
6. Checks the health endpoint answers on its address (from the router, on an isolated network) and prints how to reach it.

## After a restart

A reboot of the VM, or any restart of OpenBao, leaves it sealed: clients get errors until it is unsealed. Either redeploy the host, or unseal it by hand:

```bash
export BAO_ADDR=http://192.168.1.20:8200
bao operator unseal          # asks for a key; repeat key_threshold times
bao status                   # Sealed: false
```

## Using OpenBao

With the [bao CLI](https://openbao.org/docs/install/) (`nix shell nixpkgs#openbao`), for a host on the home network:

```bash
export BAO_ADDR=http://192.168.1.20:8200
export BAO_TOKEN=$(jq -r .root_token secrets/home/openbao-init.json)

bao kv put secret/myapp db_password=hunter2
bao kv get secret/myapp
bao kv get -field=db_password secret/myapp
```

The web UI is at `http://192.168.1.20:8200/ui`; sign in with a token. Vault clients and libraries work too: OpenBao answers Vault's API and reads `VAULT_ADDR` and `VAULT_TOKEN` as well.

For applications, don't hand out the root token. Make a policy and a token, or an [AppRole](https://openbao.org/docs/auth/approle/), per application:

```bash
bao policy write myapp - <<'EOF'
path "secret/data/myapp" { capabilities = ["read"] }
EOF
bao token create -policy=myapp -period=768h
```

### The network's secrets

Once this host is deployed, the deploys of the other hosts on its network read their secrets from `<network>/<host>` here instead of `secrets/<network>/<host>.env`, importing the file on their first deploy; the rules are in [secrets/README.md](../../secrets/README.md#networks-with-an-openbao-host). With the variables above:

```bash
bao kv get lab/gitea                                  # every key, like the .env file
bao kv get -field=GITEA_ADMIN_PASSWORD lab/gitea
bao kv patch lab/gitea GITEA_ADMIN_PASSWORD=new-one   # then redeploy gitea
bao kv metadata get lab/gitea                         # versions; bao kv rollback brings one back
bao kv list lab/                                      # every host with secrets here
```

Deploys go first to the router, then this host, then the rest, so that the others find it unsealed. After a reboot it is sealed, and their deploys stop until this host is deployed again.

### Plain HTTP

OpenBao listens on plain HTTP, so tokens and secrets cross the network unencrypted, and the deploys send the root token the same way (on an isolated network, only over the router and the network's own bridge; on a home network, over the LAN). Use it on a network you trust or an isolated one, and for HTTPS, put it behind the [proxy](../proxy/README.md) with a `proxy:` entry:

```yaml
    proxy:
      - name: bao
        port: 8200
```

Clients then use `https://bao.<domain>`, trusting the proxy's root certificate.

## On an isolated network

The network's VMs and VPN clients use `http://openbao.lab.home.arpa:8200`. To reach it from home, add a `proxy:` entry with `external: true` (HTTPS, preferred), or forward the port and redeploy the router:

```yaml
    expose:
      - port: 8200
```

## Data disk

Raft keeps everything OpenBao stores, encrypted, in `/var/lib/openbao` on the data disk.

- **Growing:** raise `data_disk.size_gb` and redeploy. The filesystem grows while OpenBao keeps running.
- **Shrinking isn't possible.** The deploy stops if the size is smaller than the current disk.
- **Redeploys never wipe it.** It is only formatted if it has no filesystem yet.
- **Backups:** `bao operator raft snapshot save backup.snap` with the root token makes a snapshot. It is encrypted, and restoring it needs the same unseal keys.

If the disk is missing at boot, the VM still starts, but OpenBao doesn't. That stops it starting over empty on the system disk.

## Making changes

Edit the host's entry or the files here and redeploy. An existing VM is updated in place; if OpenBao's configuration changed, the deploy restarts and unseals it, so clients see a short outage.

- **Port, UI, KV mounts:** change them under `settings:`. The firewall follows the port. If the host is exposed or proxied, change those ports to match.
- **Other OpenBao settings:** add them under `services.openbao.settings` in [files/configuration.nix](files/configuration.nix), such as `default_lease_ttl` or `log_level`. Leave the listener and addresses out; they come from the network file.
- **Address or network:** change `ip`, or move the entry to another network file, and redeploy. See [Moving a VM between networks](../../README.md#moving-a-vm-between-networks).

## Files

| File | Purpose |
|---|---|
| `files/configuration.nix` | NixOS configuration: OpenBao with raft storage, its user and the data disk mount |
| `templates/openbao.nix.j2` | Generated settings: listener, API address, UI, firewall |
| `tasks/` | `prepare.yml` (settings, saved keys), `configure.yml` (disk, switch, restart, init, unseal, KV mounts), `verify.yml`, `ports.yml` |
| [`../host_secrets/`](../host_secrets/tasks/main.yml) | How the other hosts' deploys read their secrets from here (the `network_secrets_store` filter in [plugins/filter/network_config.py](../../plugins/filter/network_config.py) says where) |

## Removing it

```bash
ansible-playbook playbooks/destroy-host.yaml -e network=lab -e host=openbao
```

This permanently deletes the VM, its data disk and every secret in it, including the other hosts' secrets imported from their `.env` files: any whose file you deleted after the import is lost. The playbook lists those hosts before deleting. It asks you to type the host name. Remove the entry from the network file too, or the next deploy creates it again, and move `secrets/<network>/<host>-init.json` away, or that deploy stops because the keys don't match the new, empty OpenBao.
