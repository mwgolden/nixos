# LDAP server

A NixOS VM running [lldap](https://github.com/lldap/lldap), a small LDAP server for user accounts and groups. It has a web interface for managing them, and gives other services one place to log people in.

```yaml
hosts:
  - name: ldap
    type: ldap
    vm_id: 117
    ip: 10.1.0.17
    # Optional: the web interface over HTTPS through the network's proxy.
    proxy:
      - name: users
        port: 17170
    settings:
      # All optional; these are the defaults.
      base_dn: ""        # made from the network's domain: dc=lab,dc=home,dc=arpa
      ldap_port: 3890
      http_port: 17170
```

## Secrets

Copy [env.example](env.example) to `secrets/<network>/<host>.env` and set:

| Key | Meaning |
|---|---|
| `LLDAP_ADMIN_PASSWORD` | Password of the `admin` user, at least 8 characters |
| `LLDAP_JWT_SECRET` | Signs login tokens, at least 32 random characters (`openssl rand -base64 32`) |

The deploy copies them to root-only files in `/var/lib/lldap-secrets` on the VM, and lldap reads them as systemd credentials, so they are never in the Nix store. The admin password is reset to the file's value whenever lldap starts. To change it, edit the file and redeploy. Changing the JWT secret logs everyone out of the web interface.

## Using it

The deploy ends by printing what clients need. For `lab`:

| | |
|---|---|
| Web interface | `https://users.lab.home.arpa/` through the proxy, or `http://ldap.lab.home.arpa:17170` |
| LDAP | `ldap://ldap.lab.home.arpa:3890` |
| Base DN | `dc=lab,dc=home,dc=arpa` |
| Admin bind DN | `uid=admin,ou=people,dc=lab,dc=home,dc=arpa` |
| Users / groups | `ou=people,...` / `ou=groups,...` |

Without a proxy route, the web interface's links use its plain HTTP address. With one, they use the HTTPS name.

LDAP on port 3890 is plain, not LDAPS. On an isolated network only its VMs and VPN clients can reach it. Don't `expose:` it to the home network.

## Data

Users, groups and passwords are in a SQLite file, `/var/lib/private/lldap/users.db`, on the VM's system disk. There is no separate data disk. Destroying the VM deletes them, so copy that file somewhere safe if they matter.

## Checks

After switching, the deploy checks that the `lldap` service is running. From your machine (through the router, on an isolated network) it then checks that `/health` on the web interface answers and that the LDAP port accepts connections.
