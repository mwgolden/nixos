# Database users

Creates PostgreSQL users on the postgres VM, makes sure their schemas exist, and grants each user access per schema. A user can combine several access levels and built-in roles.

| File           | Purpose                                                 |
| -------------- | ------------------------------------------------------- |
| `vars.yaml`    | Database, schemas, users and their access               |
| `.env`         | User passwords (gitignored)                             |
| `.env.example` | Template for `.env`                                     |
| `users.yaml`   | The playbook                                            |
| `users.sql.j2` | The SQL the playbook runs: schemas, roles and grants    |

## Running it

The postgres VM must be deployed first. From the repo root:

```bash
source proxmox/.env
ansible-playbook hosts/postgres/users/users.yaml
```

It reads the admin user from `hosts/postgres/.env` and connects to the VM over SSH, so no database password is needed on your machine. At the end it prints each user and the roles they have.

To list the access levels and every role that exists on the server, without changing anything:

```bash
ansible-playbook hosts/postgres/users/users.yaml --tags list
```

## Access levels

Access is granted per schema. Each level is a group role named `<database>_<schema>_<level>`, for example `adventureworks_sales_read`, and users are made members of these groups.

| Level     | Allows                                                        |
| --------- | ------------------------------------------------------------- |
| `read`    | Read tables, views and sequences (`SELECT`)                   |
| `write`   | Everything in `read`, plus `INSERT`, `UPDATE`, `DELETE` and using sequences |
| `create`  | Everything in `write`, plus creating tables, views and functions in the schema |
| `execute` | Running functions and procedures in the schema                |

Combine levels as needed, for example `[read, execute]` or `[create, execute]`.

Tables created later are covered automatically: tables, sequences and functions made by the admin users or by users with `create` on that schema get the same grants. Every run also re-grants access to everything already in the schema.

## Built-in roles

Add these under a user's `roles`. They are PostgreSQL's built-in roles, and they apply to **every database on the server**, not just `users_database`.

| Role                          | Allows                                                    |
| ----------------------------- | --------------------------------------------------------- |
| `pg_read_all_data`            | Read all tables in all schemas and databases              |
| `pg_write_all_data`           | Write all tables in all schemas and databases             |
| `pg_monitor`                  | Read monitoring views and statistics (includes the next three) |
| `pg_read_all_settings`        | Read all configuration settings                           |
| `pg_read_all_stats`           | Read all statistics views                                 |
| `pg_stat_scan_tables`         | Run monitoring functions that may lock tables             |
| `pg_signal_backend`           | Cancel queries or end sessions of other non-superusers    |
| `pg_checkpoint`               | Run `CHECKPOINT`                                          |
| `pg_maintain`                 | Run `VACUUM`, `ANALYZE`, `REINDEX` and similar on all tables (PostgreSQL 17+) |
| `pg_use_reserved_connections` | Use connection slots kept for this role (PostgreSQL 16+)  |
| `pg_create_subscription`      | Create logical replication subscriptions (PostgreSQL 16+) |
| `pg_read_server_files`        | Read files on the server. Powerful; avoid.                |
| `pg_write_server_files`       | Write files on the server. Powerful; avoid.               |
| `pg_execute_server_program`   | Run programs on the server. Powerful; avoid.              |

Any other role that already exists can be listed too, including access-level groups from another database.

## Example

`vars.yaml`:

```yaml
users_database: "Adventureworks"

schemas:
  - name: reporting        # created if missing; owner defaults to the admin user

users:
  - name: analyst
    schemas:
      - schema: sales
        access: [read]
      - schema: reporting
        access: [read, write]
    roles: [pg_monitor]

  - name: etl
    schemas:
      - schema: staging    # also created if missing
        access: [create, execute]

  - name: old_user
    state: absent
```

`.env`, with one password per user, named after the user in capitals:

```bash
ANALYST_PASSWORD=...
ETL_PASSWORD=...
```

With this, `analyst` can read `sales`, read and change data in `reporting`, and see monitoring statistics. `etl` can create and fill tables and functions in `staging`. `old_user` is dropped.

## How changes are applied

Each run brings the server in line with `vars.yaml`:

- **Users** are created if missing, and their password is set from `.env` every time. To change a password, edit `.env` and re-run.
- **Schemas** listed under `schemas` or under any user are created if missing. Existing schemas keep their owner.
- **Access is removed** when you take it out of `vars.yaml`. A user ends up with exactly the access levels and `pg_*` roles listed for them. Other role memberships, such as ones granted by hand, are left alone.
- **Users missing from `vars.yaml`** are left alone. To drop a user, set `state: absent`. Anything the user owns in `users_database` is handed to the admin user first. Dropping fails, and nothing changes, if the user still owns objects in another database.
- Everything runs in one transaction, so an error leaves the server unchanged.

The playbook prints any access it revoked and any user it dropped.

## Names

User and schema names may contain lowercase letters, digits and underscores. A user can't be named `postgres`, the admin user, or anything starting with `pg_`. `users_database` may be any existing database, for example `Adventureworks`. Group role names use it in lowercase.

Users connect like this:

```bash
psql -h 192.168.1.12 -U analyst -d Adventureworks
```
