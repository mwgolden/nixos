# Database users

A postgres host can create PostgreSQL users, make sure their schemas exist, and grant each user access per schema. A user can combine several access levels and built-in roles.

Users are set up on every deploy of the host, once `settings.users_database` is set. To apply a change to users without a full deploy, run [playbooks/postgres-users.yaml](../../playbooks/postgres-users.yaml), which does the same steps alone.

| Where | What |
|---|---|
| `settings:` of the host in `networks/<network>.yaml` | Database, schemas, users and their access |
| `secrets/<network>/<host>-users.env` | User passwords (gitignored) |
| [users-env.example](users-env.example) | Template for the passwords file |
| [tasks/users-prepare.yml](tasks/users-prepare.yml) | Reads and checks the settings and passwords, before anything changes |
| [tasks/users-apply.yml](tasks/users-apply.yml) | Applies them on the VM |
| [templates/users.sql.j2](templates/users.sql.j2) | The SQL that runs: schemas, roles and grants |

## Settings

Under the host's `settings:` in its network file:

```yaml
  - name: postgres
    type: postgres
    # ...
    settings:
      # Database the schemas live in. It must already exist, for example
      # the AdventureWorks database the deploy loads.
      users_database: Adventureworks

      # Schemas to create if missing, even if no user is listed for them
      # yet. Owner defaults to the admin user.
      schemas:
        - name: reporting
          owner: pgadmin

      users:
        - name: analyst
          schemas:
            - schema: sales
              access: [read]
            - schema: reporting
              access: [read, write]
          roles: [pg_monitor]

        - name: etl
          createdb: true
          schemas:
            - schema: staging    # also created if missing
              access: [create, execute]

        - name: old_user
          state: absent
```

Each user takes:

| Key | Meaning |
|---|---|
| `name` | Lowercase letters, digits and underscores. Required. |
| `state` | `present` (the default) or `absent`, which drops the user. |
| `createdb` | Allow the user to create databases. Default `false`. |
| `schemas` | Access levels per schema, see [Access levels](#access-levels). |
| `roles` | Extra roles, see [Built-in roles](#built-in-roles). |

Listing users or schemas without `users_database` fails the deploy before anything changes.

## Passwords

Copy [users-env.example](users-env.example) to `secrets/<network>/<host>-users.env`, such as `secrets/lab/postgres-users.env`, with one password per user, named after the user in capitals:

```bash
ANALYST_PASSWORD=...
ETL_PASSWORD=...
```

Users with `state: absent` don't need one. Passwords are set on every run, so to change one, edit the file and run again. They are sent over SSH and kept out of Ansible's output.

## Running it

Deploying the host applies the users after the admin login and AdventureWorks:

```bash
source proxmox/.env
ansible-playbook playbooks/deploy-host.yaml -e network=lab -e host=postgres
```

To apply only the users, on a host that is already deployed:

```bash
ansible-playbook playbooks/postgres-users.yaml -e network=lab -e host=postgres
```

Either way it connects to the VM over SSH (through the router, on an isolated network) and runs `psql` there as the `postgres` system user, so no database password is needed on your machine. At the end it prints each user and the roles they have.

To list the access levels and every role that exists on the server, without changing anything:

```bash
ansible-playbook playbooks/postgres-users.yaml -e network=lab -e host=postgres --tags list
```

## Access levels

Access is granted per schema. Each level is a group role named `<database>_<schema>_<level>`, for example `adventureworks_sales_read`, and users are made members of these groups.

| Level | Allows |
|---|---|
| `read` | Read tables, views and sequences (`SELECT`) |
| `write` | Everything in `read`, plus `INSERT`, `UPDATE`, `DELETE` and using sequences |
| `create` | Everything in `write`, plus creating tables, views and functions in the schema |
| `execute` | Running functions and procedures in the schema |

Combine levels as needed, for example `[read, execute]` or `[create, execute]`.

Objects created later are covered automatically: tables, sequences and functions made by the admin users or by users with `create` on that schema get the same grants. Every run also re-grants access to everything already in the schema.

## Built-in roles

Add these under a user's `roles`. They are PostgreSQL's built-in roles, and they apply to **every database on the server**, not just `users_database`.

| Role | Allows |
|---|---|
| `pg_read_all_data` | Read all tables in all schemas and databases |
| `pg_write_all_data` | Write all tables in all schemas and databases |
| `pg_monitor` | Read monitoring views and statistics (includes the next three) |
| `pg_read_all_settings` | Read all configuration settings |
| `pg_read_all_stats` | Read all statistics views |
| `pg_stat_scan_tables` | Run monitoring functions that may lock tables |
| `pg_signal_backend` | Cancel queries or end sessions of other non-superusers |
| `pg_checkpoint` | Run `CHECKPOINT` |
| `pg_maintain` | Run `VACUUM`, `ANALYZE`, `REINDEX` and similar on all tables (PostgreSQL 17+) |
| `pg_use_reserved_connections` | Use connection slots kept for this role (PostgreSQL 16+) |
| `pg_create_subscription` | Create logical replication subscriptions (PostgreSQL 16+) |
| `pg_read_server_files` | Read files on the server. Powerful; avoid. |
| `pg_write_server_files` | Write files on the server. Powerful; avoid. |
| `pg_execute_server_program` | Run programs on the server. Powerful; avoid. |

Any other role that already exists can be listed too, including access-level groups from another database.

With the example above, `analyst` can read `sales`, read and change data in `reporting`, and see monitoring statistics. `etl` can create databases, and create and fill tables and functions in `staging`. `old_user` is dropped.

## How changes are applied

Each run brings the server in line with the settings:

- **Users** are created if missing, and their password is set from the secrets file every time.
- **Schemas** listed under `schemas` or under any user are created if missing. Existing schemas keep their owner.
- **Access is removed** when you take it out of the settings. A user ends up with exactly the access levels and `pg_*` roles listed for them. Other role memberships, such as ones granted by hand, are left alone.
- **Users missing from the list** are left alone. To drop a user, set `state: absent`. Anything the user owns in `users_database` is handed to the admin user first. Dropping fails, and nothing changes, if the user still owns objects in another database.
- The schemas, roles and grants run in one transaction, so an error leaves them unchanged. Passwords are set right after, in a separate step.

The run prints any access it revoked and any user it dropped.

## Names

User and schema names may contain lowercase letters, digits and underscores. A user can't be named `postgres`, the admin user, or anything starting with `pg_`. `users_database` may be any existing database, for example `Adventureworks`. Group role names use it in lowercase, with other characters turned into underscores.

## Connecting

Users connect to `users_database`. On a home network:

```bash
psql -h 192.168.1.12 -U analyst -d Adventureworks
```

On an isolated network, VMs on it and VPN clients connect to the host's name, such as `postgres.lab.home.arpa`. From home, connect to the router's WAN address on the port in the host's `expose:` entry:

```bash
psql -h 192.168.1.13 -p 5432 -U analyst -d Adventureworks
```

Password logins are allowed only from the host's allowed networks; see [Who may log in](README.md#who-may-log-in).
