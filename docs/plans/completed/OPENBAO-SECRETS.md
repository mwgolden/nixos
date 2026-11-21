# Plan: keep a network's secrets in its OpenBao

Every host's secrets are now read from files on this machine: `secrets/<network>/<host>.env` (and `<host>-users.env` for postgres), through the [dotenv](../../roles/dotenv/tasks/main.yml) role. Since `1b1f36b` a network can also have an [openbao](../../roles/openbao/README.md) host, but nothing uses it: the deploys still read only the files.

This plan makes a network that has an `openbao` host keep its hosts' secrets there. Deploys read each host's secrets from OpenBao, and the `.env` files become a way to put secrets in, not where they live. Networks without an `openbao` host keep working exactly as now.

## Progress

**Phases 1 to 4 done (2026-11-16); phase 5's live checks are still to run.** All decisions in [section 6](#6-decisions) are made.

- Phase 1: `network_secrets_store`, the one-openbao and mount-name checks, and the new deploy order are in [network_config.py](../../plugins/filter/network_config.py), with tests in `tests/test_network_config.py` and `tests/test_inventory_placement.py`.
- Phase 2: the openbao role always mounts `<network>/`, checks the root token on every deploy, and refuses the network's name in `kv_mounts`.
- Phase 3: [roles/host_secrets](../../roles/host_secrets/tasks/main.yml) and the `host_secrets_decide` / `host_secrets_diff` filters in [host_secrets.py](../../plugins/filter/host_secrets.py) (tests in `tests/test_host_secrets.py`). Every type's `prepare.yml` and postgres's `users-prepare.yml` use it; `postgres-users.yaml` adds the routers to its inventory for it. `dotenv` got `dotenv_required`. The role was run through every state of section 2's table and every rule of section 1 against a stand-in for OpenBao's API, not a real OpenBao.
- Phase 4: messages use `host_secrets_where`; docs updated as listed in 3.5, plus `destroy-host.yaml`'s confirmation and a warning naming the hosts whose only secrets are in the OpenBao being deleted.
- Phase 5: not run yet (needs Proxmox and the `agent-developer` network, which has no openbao host in its file yet). The unit suite and `--syntax-check` on every playbook pass.

## 1. Target

```yaml
# networks/agent-developer.yaml
hosts:
  - name: router
    type: router
    ...
  - name: openbao            # its presence turns the feature on for this network
    type: openbao
    vm_id: 306
    ip: 10.3.1.5
    data_disk: {size_gb: 10, storage: local-lvm}
  - name: gitea
    type: gitea
    ...
```

```bash
ansible-playbook playbooks/deploy-network.yaml -e network=agent-developer
```

- **The router deploys first, then OpenBao, then the rest** in file order. OpenBao has no `.env` of its own, so it doesn't depend on itself.
- **Each host's secrets are at `<network>/<host>`** in OpenBao, such as `agent-developer/gitea`: a KV version 2 mount named after the network, one secret per file, its keys the same as the file's (`GITEA_ADMIN_USER`, `GITEA_ADMIN_PASSWORD`, ...). Postgres users are at `<network>/<host>-users`. The mapping is one-to-one with today's file names, so the existing `env.example` files and checks still describe them.
- **Importing:** if `secrets/<network>/<host>.env` exists and OpenBao has nothing at `<network>/<host>`, the deploy writes the file's values there and says so. After that the file can be deleted; the deploy says that too.
- **Reading:** if OpenBao has the secret, the deploy uses it, whether or not the file exists.
- **Conflicts:** if both exist and differ, the deploy stops and names the keys that differ (never the values). `-e secrets_push=true` makes the file win and overwrites OpenBao (a new KV version, so the old one is still recoverable with `bao kv rollback`).
- **Changing a secret** afterwards: `bao kv patch agent-developer/gitea GITEA_ADMIN_PASSWORD=...` and redeploy the host, or edit the file and redeploy with `-e secrets_push=true`.

What stays a file, on purpose:

- `<openbao>-init.json`: the unseal keys and root token. They unlock OpenBao, so they can't live in it.
- `<proxy>-ca.crt` and `vpn/`: written by deploys and handed to your own machines. Mirroring them into OpenBao is a possible later step ([section 7](#7-later)), not part of this plan.
- `proxmox/.env`.

## 2. Reaching OpenBao from the deploy

`prepare.yml` runs on localhost, before the host's VM is touched. The secrets lookup goes there.

- **Address:** `http://<openbao ip>:<port>`, from the openbao host's inventory entry. On an isolated network this machine can't reach it, so the requests are delegated to the router (`final.via_router`), exactly as [openbao's verify.yml](../../roles/openbao/tasks/verify.yml) already does for its health check.
- **Token:** the root token from `secrets/<network>/<openbao>-init.json`.
- **Plain HTTP:** on an isolated network the token crosses only the router and the network's own bridge. On a flat network (`home`) it crosses the LAN. The openbao README already warns about this; this plan adds a line saying the deploy sends the root token too.
- **No secret is logged:** every task that holds a token or a value has `no_log: true`, as the dotenv role does today.

When OpenBao can't be used, the deploy behaves like this:

| State | What the deploy does |
|---|---|
| No `openbao` host in the network file | Files only, as today |
| `openbao` host listed, but no `-init.json` yet (never deployed) | Files only, with a warning that OpenBao isn't deployed yet. This is what lets a single `deploy-host` of gitea work before OpenBao exists. |
| `-init.json` exists, OpenBao unreachable or sealed | Stops: "OpenBao on <host> is sealed or down; deploy it first (`deploy-host -e host=openbao`)". No silent fallback to the file, which might be stale. |
| Token refused | Stops, with the same "make a new root token" hint openbao's configure.yml gives |

## 3. Changes

### 3.1 Network files and inventory ([plugins/filter/network_config.py](../../plugins/filter/network_config.py))

- **Validation:** at most one `openbao` host per network. Two is an error ("a network can have only one openbao host; it holds the network's secrets").
- **Network name as a mount path:** a network with an openbao host needs a name OpenBao accepts as a mount: up to 63 lowercase letters, digits, `_` and `-`, and not `sys`, `auth`, `identity` or `cubbyhole` (the same rule openbao's `prepare.yml` already applies to `kv_mounts`). Today's names (`home`, `lab`, `agent-developer`, `workstation-lab`) all pass.
- **New filter `network_secrets_store(inventory, network)`:** returns `{host_id, name, url, via_router, init_file}` for the network's openbao host, or `{}` when there is none. One place that decides; the role and the docs refer to it.
- **`network_config_deploy_order`:** router first, then openbao hosts, then the rest in file order. Today it is router then file order.

### 3.2 OpenBao host ([roles/openbao](../../roles/openbao/))

- **Always mount `<network>`** (KV v2), the openbao host's own network name (`vm.network.name`), separately from `kv_mounts`. Removing anything from `kv_mounts` then can't break deploys, and the user's own `secret/` mount stays theirs.
- `kv_mounts: []` no longer means "the deploy doesn't need the root token": the network mount and every other host's deploy need it. Update the README's sentence about revoking the root token, and the "root token refused" message.
- **Validation:** the network name isn't allowed in `kv_mounts` (it would be mounted twice).

### 3.3 New role `host_secrets` (replaces direct `dotenv` calls)

One role that every type's `prepare.yml` calls instead of `dotenv`:

```yaml
- name: Read the Gitea admin login
  ansible.builtin.include_role:
    name: host_secrets
  vars:
    host_secrets_name: "{{ vm.name }}"           # or "{{ vm.name }}-users"
    host_secrets_missing_hint: "Copy roles/gitea/env.example there and set the admin login."
    host_secrets_required: true                  # false for workstation
```

It sets the same `dotenv_values` fact the role tasks use today, so each type's checks and `set_fact` lines don't change; only the include does.

Steps:

1. Look up the store with `network_secrets_store`. None, or not deployed yet: include `dotenv` on `secrets/<network>/<name>.env` and stop here (today's behaviour).
2. Read the file if it exists (through `dotenv`, with its missing-file assert turned off).
3. `GET /v1/<network>/data/<name>` from OpenBao (delegated to the router when isolated). 404 means not there yet.
4. Decide, per section 1: use OpenBao's, import the file's, push the file's with `secrets_push`, or stop on a conflict or on neither existing (with `host_secrets_missing_hint`, now naming both places).
5. Write with `POST /v1/<network>/data/<name>` when importing or pushing. Compare by keys and values in a filter (`host_secrets_diff`, returning only key names) so nothing secret ends up in a message.
6. Set `dotenv_values` and a short `host_secrets_source` fact (`file`, `openbao`, `imported`, `pushed`) for the deploy message.

Callers to switch: `prepare.yml` of gitea, postgres, garage, ldap, nats, monitoring and workstation, and postgres `users-prepare.yml` (also used by [postgres-users.yaml](../../playbooks/postgres-users.yaml), which then needs the router and openbao hosts in its inventory to delegate to; check whether `network_config`'s inventory task already adds them).

The `dotenv` role stays, as the file reader `host_secrets` uses.

### 3.4 Messages

- `verify.yml` messages that say "password in `secrets/<network>/<host>.env`" (gitea, postgres, ldap, nats, monitoring, garage) change to name where the secret actually is: the file, or `bao kv get <network>/<host>` on `<openbao url>`. A small shared template or a fact from `host_secrets` (`host_secrets_where`) keeps that to one line per role.
- After an import: "Imported secrets/<network>/<host>.env into OpenBao at <network>/<host>. OpenBao is now where it's read from; you can delete the file (back up `<openbao>-init.json` first)."

### 3.5 Docs

- [secrets/README.md](../../secrets/README.md): a section "Networks with an OpenBao host", with the import, read and conflict rules and the table from section 2.
- [roles/openbao/README.md](../../roles/openbao/README.md): the network mount (named after the network), that other deploys use the root token, and how to read or change a host's secrets with `bao`.
- [networks/README.md](../../networks/README.md) and [docs/ARCHITECTURE.md](../ARCHITECTURE.md): the deploy order, and that an openbao host changes where secrets come from.
- `deploy-host.yaml` and `deploy-network.yaml` header comments: "Secrets are read from secrets/<network>/<host>.env" becomes "... or the network's OpenBao".

## 4. Phases

1. **Inventory and order:** `network_secrets_store`, the one-openbao check, the new deploy order. Unit tests in `tests/test_network_config.py`.
2. **OpenBao host:** the network mount and its check. Live: redeploy an openbao host and `bao secrets list` shows `<network>/`.
3. **`host_secrets` role** and `host_secrets_diff` filter, with unit tests for the decision (file only, store only, equal, different, neither, push). Switch gitea first and try it live; then the other types.
4. **Messages and docs.**
5. **Live checks on `agent-developer`** (it has `gitea.env` and `garage.env` today):
   1. Add an `openbao` host, `deploy-network`: OpenBao deploys second; gitea and garage report "imported".
   2. Redeploy: both report "openbao". Move the two `.env` files away and redeploy again: still works.
   3. Put a different password in a restored `gitea.env`: the deploy stops naming `GITEA_ADMIN_PASSWORD`. `-e secrets_push=true` succeeds; `bao kv metadata get agent-developer/gitea` shows a new version.
   4. Reboot the openbao VM (it comes up sealed) and `deploy-host -e host=gitea`: it stops with the "sealed" message. Deploy openbao, then gitea works.
   5. `deploy-network -e network=lab` (no openbao) behaves exactly as before.
   6. Run the full unit suite and `--syntax-check` on every playbook.

## 5. Things this changes for existing setups

- **A network that already has an openbao host** starts importing on its next deploy. Nothing is lost: files are only read, never deleted by the deploy.
- **Moving a host to another network** (its entry to another file): its secrets are looked up in the new network's store or `secrets/<new network>/`, which today is also true for files. Note it in [MOVING-HOSTS.md](../MOVING-HOSTS.md): copy with `bao kv get -format=json` / `bao kv put`, or keep the `.env` file and let the new network import it.
- **Renaming a network** makes the next deploy mount a new, empty `<new name>/` and look there, while the secrets stay under the old name. Copy them across with `bao kv get` / `bao kv put` first, or keep the `.env` files so they are imported again.
- **Destroying a host** leaves its `<network>/<host>` secret, as it leaves the `.env` file. Destroying the openbao host loses every imported secret whose file was deleted; [destroy-host](../../playbooks/destroy-host.yaml)'s confirmation for an openbao host should say so.

## 6. Decisions

1. **Where the truth is. Decided:** OpenBao, once a secret is in it. Files are imported, and a differing file stops the deploy unless `secrets_push=true`.
2. **Which token the deploy uses. Decided:** the root token from `-init.json`. A narrower `deploy` policy and token, so the root token can be revoked, is left for [later](#7-later).
3. **More than one openbao host in a network. Decided:** not allowed; validation fails.
4. **Mount name. Decided:** the network's name, so a host's secrets are at `<network>/<host>`. It is separate from the user's `secret/` mount.
5. **Single `deploy-host` before OpenBao exists. Decided:** read the `.env` file and print a warning that OpenBao isn't deployed yet (section 2).

## 7. Later

Not in this plan, but it makes them possible:

- **A narrower deploy token:** the openbao deploy writes a `deploy` policy (read and write on `<network>/*` only) and a periodic token to `secrets/<network>/<openbao>-deploy-token`, so the root token can be revoked.
- **VMs reading their own secrets at runtime**, with an AppRole per host and a policy limited to `<network>/<host>`, instead of the deploy writing them into NixOS configuration or files on the VM.
- **Generated secrets:** when neither the file nor OpenBao has a value the role can safely invent (Grafana's secret key, lldap's JWT secret, a Garage key pair), generate it, store it in OpenBao, and skip the file entirely.
- **Mirroring deploy-written files** (`vpn/` keys, the proxy CA) into OpenBao as a backup.
