# Secrets

Credentials for each host, one folder per network:

```text
secrets/<network>/<host>.env          # read by the host's deploy
secrets/<network>/<host>-users.env    # postgres only: database user passwords
secrets/<network>/<proxy>-ca.crt      # written by deploys: the proxy's root certificate
secrets/<network>/vpn/                # written by deploys: WireGuard keys and client files
```

Everything here except this README is gitignored. Each file holds `KEY=value` lines. `export ` and quotes around values are optional.

| Host type | File | Example |
|---|---|---|
| gitea | `<host>.env`: the admin login | [roles/gitea/env.example](../roles/gitea/env.example) |
| postgres | `<host>.env`: the admin login | [roles/postgres/env.example](../roles/postgres/env.example) |
| postgres | `<host>-users.env`: one `<USER>_PASSWORD` per user | [roles/postgres/users-env.example](../roles/postgres/users-env.example) |
| garage | `<host>.env`: the S3 access key | [roles/garage/env.example](../roles/garage/env.example) |
| ldap | `<host>.env`: the admin password and JWT secret | [roles/ldap/env.example](../roles/ldap/env.example) |
| nats | `<host>.env`: the client login | [roles/nats/env.example](../roles/nats/env.example) |

Two kinds of file here are written by deploys, not by you:

- `<proxy>-ca.crt`: the root certificate of a [proxy](../roles/proxy/README.md#https), for your machines to trust. Not secret.
- `vpn/`: the router's [VPN](../roles/router/README.md#vpn) keys, made on the first deploy and kept after that. `<name>.key` files are private keys. `<peer>.conf` files are ready-to-use client configurations, and contain the peer's private key. Deleting `<router>.key` makes a new router key on the next deploy, and every client file has to be handed out again.

Proxmox and SSH key settings are still in `proxmox/.env`.
