# Secrets

Credentials for each host, one folder per network:

```text
secrets/<network>/<host>.env          # read by the host's deploy
secrets/<network>/<host>-users.env    # postgres only: database user passwords
```

Everything here except this README is gitignored. Each file holds `KEY=value` lines. `export ` and quotes around values are optional.

| Host type | File | Example |
|---|---|---|
| gitea | `<host>.env`: the admin login | [roles/gitea/env.example](../roles/gitea/env.example) |
| postgres | `<host>.env`: the admin login | [roles/postgres/env.example](../roles/postgres/env.example) |
| postgres | `<host>-users.env`: one `<USER>_PASSWORD` per user | [roles/postgres/users-env.example](../roles/postgres/users-env.example) |
| garage | `<host>.env`: the S3 access key | [roles/garage/env.example](../roles/garage/env.example) |

Proxmox and SSH key settings are still in `proxmox/.env`.
