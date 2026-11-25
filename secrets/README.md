# Secrets

Credentials for each host, one folder per network:

```text
secrets/<network>/<host>.env           # read by the host's deploy, or imported into the network's OpenBao (below)
secrets/<network>/<host>-users.env     # postgres only: database user passwords
secrets/<network>/<openbao>-init.json  # written by deploys: OpenBao's unseal keys and root token
secrets/<network>/<openbao>-tls.crt    # written by deploys: what clients trust to reach OpenBao (tls: self-signed or pki)
secrets/<network>/<openbao>-pki-root.crt       # written by deploys: its TLS root (settings.pki), the one file your machines trust
secrets/<network>/<openbao>-pki-<net>.crt      # written by deploys: its intermediate for network <net>
secrets/<network>/<openbao>-ssh-user-ca.pub  # written by deploys: its SSH user CA's public key
secrets/<network>/<openbao>-ssh-host-ca.pub  # written by deploys: its SSH host CA's public key
secrets/<network>/<openbao>-deploy-token     # written by deploys: the token other deploys read secrets with
secrets/<network>/<host>-read-token          # written by deploys: a host's read-only token, also on the VM
secrets/<network>/backups/                   # written by backups: OpenBao snapshots
secrets/<network>/<proxy>-ca.crt       # written by deploys: the proxy's own root certificate (pki: proxy-internal)
secrets/<network>/vpn/                 # written by deploys: WireGuard keys and client files
```

Everything here except this README is gitignored. Each file holds `KEY=value` lines. `export ` and quotes around values are optional.

| Host type | File | Example |
|---|---|---|
| gitea | `<host>.env`: the admin login | [roles/gitea/env.example](../roles/gitea/env.example) |
| gitea_runner | none: it reads its gitea host's admin login to get a registration token | |
| postgres | `<host>.env`: the admin login | [roles/postgres/env.example](../roles/postgres/env.example) |
| postgres | `<host>-users.env`: one `<USER>_PASSWORD` per user | [roles/postgres/users-env.example](../roles/postgres/users-env.example) |
| garage | `<host>.env`: the S3 access key | [roles/garage/env.example](../roles/garage/env.example) |
| ldap | `<host>.env`: the admin password and JWT secret | [roles/ldap/env.example](../roles/ldap/env.example) |
| nats | `<host>.env`: the client login | [roles/nats/env.example](../roles/nats/env.example) |
| monitoring | `<host>.env`: Grafana's admin password and secret key | [roles/monitoring/env.example](../roles/monitoring/env.example) |
| workstation | `<host>.env`, optional: the user's password hash, and secret environment variables (`WORKSTATION_ENV_<NAME>`) | [roles/workstation/env.example](../roles/workstation/env.example) |

These files are written by deploys, not by you:

- `<proxy>-ca.crt`: the root certificate of a [proxy](../roles/proxy/README.md#https) on a network without `security.pki` from an OpenBao, for your machines to trust. Not secret. No longer written, nor needed, once the network uses an OpenBao root.
- `<openbao>-init.json`: an [OpenBao](../roles/openbao/README.md#unseal-keys-and-root-token) host's unseal keys and root token, made on its first deploy. Without it a sealed OpenBao can't be opened, so back it up elsewhere. Never overwritten.
- `<openbao>-tls.crt`: what clients trust to reach an [OpenBao](../roles/openbao/README.md#https) host over HTTPS (`BAO_CACERT`): its certificate with `tls: self-signed`, replaced when it makes a new one; a copy of its network's TLS root with `tls: pki`. Not secret.
- `<openbao>-pki-root.crt`: the [TLS root](../roles/openbao/README.md#tls-certificates) of an OpenBao host with `settings.pki`. Trust it once on your machines; it covers every network that uses it. Not secret, but guarded like the SSH CA keys: a deploy stops if OpenBao's root no longer matches it.
- `<openbao>-pki-<net>.crt`: that root's intermediate for network `<net>`. Hosts' deploys check their certificates against it. Rewritten when the intermediate is signed again.
- `<openbao>-ssh-user-ca.pub`: the public key of an OpenBao host's [SSH user CA](../roles/openbao/README.md#ssh-certificates). Not secret, but the deploys of every network that trusts the CA write it onto their hosts, so it is never overwritten: a deploy stops if the CA's key no longer matches it.
- `<openbao>-ssh-host-ca.pub`: the public key of an OpenBao host's [SSH host CA](../roles/openbao/README.md#ssh-host-certificates), which your SSH client trusts through `scripts/ssh-cert --trust-hosts`. Guarded the same way.
- `<openbao>-deploy-token` and `<host>-read-token`: an OpenBao host's [tokens](../roles/openbao/README.md#the-networks-tokens) for its network's deploys, and for each host to read its own secrets. Secret. Made again when missing or revoked.
- `backups/<openbao>-<time>.snap`: [snapshots](../roles/openbao/README.md#backups) of an OpenBao. Encrypted, but restoring one needs `<openbao>-init.json`; keep both, off this machine.
- `vpn/`: the router's [VPN](../roles/router/README.md#vpn) keys, made on the first deploy and kept after that. `<name>.key` files are private keys. `<peer>.conf` files are ready-to-use client configurations, and contain the peer's private key. Deleting `<router>.key` makes a new router key on the next deploy, and every client file has to be handed out again.

Proxmox and SSH key settings are still in `proxmox/.env`.

## Networks with an OpenBao host

A network with a host of type [openbao](../roles/openbao/README.md) keeps its hosts' secrets there, and the `.env` files become a way to put secrets in rather than where they live. Each host's secrets are at `<network>/<host>` in a KV version 2 mount named after the network (postgres users at `<network>/<host>-users`), with the same keys as the file, so the `env.example` files still describe them. `deploy-network` deploys the router first, then the openbao host, then the rest. Networks without an openbao host read only the files.

On every deploy of a host, [roles/host_secrets](../roles/host_secrets/tasks/main.yml) does this:

| File | OpenBao | What happens |
|---|---|---|
| exists | nothing yet | **Imported:** the file's values are written to OpenBao, and the deploy says you can delete the file. |
| any | has the secret, same as the file or no file | **Read from OpenBao.** |
| differs | has the secret | **Stops**, naming the keys that differ (never the values). `-e secrets_push=true` makes the file win: it is written as a new version, and `bao kv rollback` brings the old one back. |
| missing | nothing | Stops, with the usual hint to copy `env.example`. |

To change a secret afterwards, either `bao kv patch <network>/<host> KEY=value` and redeploy the host, or edit the file and redeploy with `-e secrets_push=true`. To read one: `bao kv get <network>/<host>` (see [Using OpenBao](../roles/openbao/README.md#using-openbao) for `BAO_ADDR` and `BAO_TOKEN`).

The deploy reaches OpenBao with the network's deploy token (`<openbao>-deploy-token`), or the root token from `<openbao>-init.json` until that exists, through the network's router on an isolated network. When it can't:

| State | What the deploy does |
|---|---|
| No openbao host in the network file | Files only, as above |
| An openbao host listed, but no `-init.json` yet (never deployed) | Files only, with a warning that OpenBao isn't deployed yet. This lets one host be deployed before OpenBao. |
| `-init.json` exists, but OpenBao is unreachable or sealed (it comes up sealed after a reboot) | Stops: deploy the openbao host first, which unseals it. There is no fallback to the file, which might be stale. |
| The root token was revoked | Stops, with the hint to make a new one (`bao operator generate-root`) |

What stays a file, on purpose: `<openbao>-init.json` (it unlocks OpenBao, so it can't live in it), `<proxy>-ca.crt`, the `-pki-` certificates and `vpn/` (written by deploys, handed to your own machines), and `proxmox/.env`.

Destroying the openbao host deletes every secret in it: any host whose `.env` file you deleted after the import then has no secrets anywhere. Destroying a host leaves its `<network>/<host>` secret, as it leaves the file. Moving a host to another network, or renaming a network, means its secrets are looked up in the new network's store, as with files; see [MOVING-HOSTS.md](../docs/MOVING-HOSTS.md#secrets-are-found-by-name).
