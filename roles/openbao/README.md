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
      tls: none            # or self-signed: HTTPS, see "HTTPS" below
      admin_sources: []    # addresses or subnets allowed to reach the port; [] is anyone
      # An SSH user CA for administrators; see "SSH certificates" below.
      ssh_user_ca: false   # needs tls
      ssh_cert_max_ttl: 24h
      ssh_host_ca: false   # an SSH host CA too; see "SSH host certificates"; needs tls
      ssh_host_cert_ttl: 8760h
      admin_mfa: false     # true: every admin also enters a TOTP code
      admins: []           # [{name: alice, roles: [homelab-admin], mfa: true}]
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

### HTTPS

With `tls: self-signed`, the deploy makes a key and a certificate (P-256, valid for 2 years) on the VM, for its address, `127.0.0.1`, its name and its DNS name. The key stays in `/etc/openbao/tls`, readable only by root; systemd hands both to OpenBao (`LoadCredential`). The certificate is copied to `secrets/<network>/<host>-tls.crt`, which clients trust:

```bash
export BAO_ADDR=https://192.168.1.20:8200
export BAO_CACERT=secrets/home/openbao-tls.crt
```

A new certificate is made when fewer than 30 days are left or the names change (another address), and OpenBao is restarted and unsealed to use it. Clients then need the new file. `tls: pki`, a certificate from the network's TLS intermediate, comes with phase 4 of [docs/plans/NETWORK-SECURITY.md](../../docs/plans/NETWORK-SECURITY.md).

`admin_sources` limits who can reach the port, such as `[192.168.1.50]` for one desktop. Include the machine you deploy from: the deploy's own check of the port runs there (from the router on an isolated network, which is already in the network's subnet).

### Plain HTTP

Without `tls`, OpenBao listens on plain HTTP, so tokens and secrets cross the network unencrypted, and the deploys send the root token the same way (on an isolated network, only over the router and the network's own bridge; on a home network, over the LAN). Use it on a network you trust or an isolated one, and for HTTPS, put it behind the [proxy](../proxy/README.md) with a `proxy:` entry:

```yaml
    proxy:
      - name: bao
        port: 8200
```

Clients then use `https://bao.<domain>`, trusting the proxy's root certificate.

## SSH certificates

With `ssh_user_ca: true` (and `tls`), OpenBao signs short-lived SSH certificates for administrators. Networks whose `security:` block names this host as `administrative_identity.instance` trust it: each of their hosts gets the CA's public key and a list of accepted principals per user, and static keys keep working. The design is in [docs/ARCHITECTURE.md §12.3](../../docs/ARCHITECTURE.md#123-administrative-access); the network side is in [networks/README.md](../../networks/README.md#security).

Every deploy of this host:

1. Mounts an SSH engine at `ssh-client-signer/` and makes its CA key inside OpenBao (ed25519) if there's none. The key never leaves OpenBao.
2. Writes the public key to `secrets/<network>/<host>-ssh-user-ca.pub`, where the other hosts' deploys read it. They never contact OpenBao, so deploys and logins keep working while it's down. If the CA's key ever differs from that file (a wiped data disk), the deploy stops rather than make hosts trust a new key; move the file away to accept it, then redeploy every host that trusts it.
3. Writes one signing role per principal: `homelab-admin`, and `<network>-admin` and `<network>-operator` for every network that trusts it (or those networks' own `principals`). Certificates last `ssh_cert_max_ttl` (24h), and longer ones are refused. Admin certificates allow a terminal and port forwarding (`ssh -J` through an isolated network's router needs it, and they give root anyway); operator certificates allow a terminal only. Each certificate's key ID is `userpass-<admin>-<role>`, and the hosts' sshd logs show it.
4. Sets up `admins`: a `userpass` login each, with a policy that signs its `roles` and nothing else, and 15-minute tokens. An admin removed from the list keeps the login but can't sign anything.
5. With MFA on for any admin (`admin_mfa`, or the admin's own `mfa:`), makes a TOTP method and requires it for those admins only. With none, the requirement is removed; enrolments stay, so turning it on again needs no new code.
6. Records every request in an audit log, `/var/lib/openbao/audit.log` on the data disk, with secrets hashed.

### Adding an administrator

The deploy never sets passwords or TOTP codes. With the root token (`BAO_TOKEN=$(jq -r .root_token secrets/<network>/<host>-init.json)`, plus `BAO_ADDR` and `BAO_CACERT` as above):

1. Add `{name: alice, roles: [homelab-admin, lab-admin]}` to `admins` and deploy this host. Roles must be ones this CA signs; the deploy says which.
2. Make the login; it asks for the password: `bao write auth/userpass/users/alice password=-`
3. Deploy this host again, which gives the login its policy.
4. With MFA on: once, `bao write identity/mfa/method/totp/admin-generate method_id=<id> entity_id=<id>`. The deploy prints the command with both IDs. Scan the `url` in its answer (`otpauth://...`) with an authenticator app, preferably on your phone, not the machine your SSH key is on. The app shows an ID as the account name; rename it. Running it again makes a new code and the old one stops working. An admin who needs MFA can't log in until enrolled.

To change a password: `bao write auth/userpass/users/alice/password password=-`.

### Getting a certificate

[scripts/ssh-cert](../../scripts/ssh-cert) needs the [bao CLI](https://openbao.org/docs/install/) on your machine:

```bash
scripts/ssh-cert --user alice homelab-admin lab-admin   # password (and TOTP code), then one file per role
scripts/ssh-cert --list                                 # what you have and when it expires
scripts/ssh-cert --config home lab >> ~/.ssh/config     # once: which certificate each network's hosts get
ssh admin@192.168.1.18
```

Certificates go to `~/.ssh/nixlab/<role>-cert.pub`, one per role, so asking for one doesn't replace another. The `--config` blocks set `IdentitiesOnly yes` and list only the network's certificates, because each one offered counts against sshd's 6 attempts. A home network's block matches its whole subnet (`192.168.1.*`), so it applies to every SSH connection to that range from your machine; trim it to the hosts you want if you use other keys there.

To reach a host on an isolated network, jump through its router with an admin certificate: `ssh -J admin@<router wan_ip> admin@<host ip>`, or use its VPN.

### SSH host certificates

With `ssh_host_ca: true` as well, this host also runs an SSH host CA (`ssh-host-signer/`, its public key in `secrets/<network>/<host>-ssh-host-ca.pub`), with one signing role per network that sets `administrative_identity.ssh_host_ca: true`. That role, `hosts-<network>`, may only sign that network's hosts' names and addresses.

Each such host's deploy then gets it a certificate for its own host key, valid for `ssh_host_cert_ttl` (a year), for its name, `<name>.<domain>` and its address (and a router's WAN address). The deploy keeps a certificate while it is for the same key, CA and names with more than 30 days left, and otherwise asks this host for a new one, from the machine you deploy from. If this host is down, it warns and keeps the old one.

Your SSH client then trusts every such host without asking, and refuses one whose certificate doesn't name the address or name you used:

```bash
scripts/ssh-cert --trust-hosts home lab >> ~/.ssh/known_hosts
```

That adds one `@cert-authority` line per network. A host with a certificate is also still accepted by a `known_hosts` entry for its key. This CA deploys its own certificate only on its second deploy, since the CA doesn't exist yet during the first one.

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
| `templates/openbao.nix.j2` | Generated settings: listener (and its TLS), API address, UI, audit log, firewall |
| `tasks/` | `prepare.yml` (settings, saved keys), `configure.yml` (disk, switch, restart, init, unseal, KV mounts), `tls.yml` (the listener's certificate), `ssh-ca.yml` (the SSH user CA and its roles), `admins.yml` (logins, policies, MFA), `verify.yml`, `ports.yml` |
| [`../host_secrets/`](../host_secrets/tasks/main.yml) | How the other hosts' deploys read their secrets from here (the `network_secrets_store` filter in [plugins/filter/network_config.py](../../plugins/filter/network_config.py) says where) |

## Removing it

```bash
ansible-playbook playbooks/destroy-host.yaml -e network=lab -e host=openbao
```

This permanently deletes the VM, its data disk and every secret in it, including the other hosts' secrets imported from their `.env` files: any whose file you deleted after the import is lost. The playbook lists those hosts before deleting. It asks you to type the host name. Remove the entry from the network file too, or the next deploy creates it again, and move `secrets/<network>/<host>-init.json` away, or that deploy stops because the keys don't match the new, empty OpenBao.

If this host is an SSH user CA, no one can get new certificates afterwards, on any network that trusts it; logins with static keys keep working. `secrets/<network>/<host>-ssh-user-ca.pub` stays, and a new CA on the same host stops at it until you move it away (then redeploy every host that trusts the new one).
