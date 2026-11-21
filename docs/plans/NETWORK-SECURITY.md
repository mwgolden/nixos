# Plan: network identity, secrets and certificate authorities

The architecture is in [ARCHITECTURE.md §12](../ARCHITECTURE.md#12-identity-secrets-and-certificate-authorities). This plan says how to get there from what the repository does today.

In short: each network file gets an optional `security:` block. It says which authority signs administrators' SSH certificates, where the hosts' secrets live, and who issues TLS certificates. A home OpenBao becomes the SSH user CA, and is the only shared authority. Isolated networks keep their own OpenBao for secrets and, later, their own TLS intermediate CA under an offline root. A network without a `security:` block works exactly as it does now.

## Progress

**Proposed on 2026-11-21. Not approved yet.** Every decision in [section 7](#7-decisions) was made on 2026-11-21: 1 to 3 and 5 to 13 as recommended, 4 as optional MFA, off by default, and 14 as one certificate file per role.

| Phase | What it delivers | Status |
|---|---|---|
| 1 | `security:` schema, presets, validation. No change in behaviour | **done** (2026-11-21) |
| 2 | Home OpenBao with TLS, SSH user CA, password login with optional MFA, hosts trust the CA, desktop script | **done** (2026-11-21), except running `scripts/ssh-cert` itself |
| 2b | Unique SSH host keys per VM, then an SSH host CA | **done** (2026-11-21) |
| 3 | Network-local OpenBao hardening: deploy token, TLS, backups, isolation and outage checks | not started |
| 4 | Offline root CA, per-network intermediates, the proxy gets certificates from OpenBao | not started |
| 5 | `independent` strategy, switching authorities | not started |

Phase 1 is in [network_config.py](../../plugins/filter/network_config.py): `check_security`, `check_openbao_authority`, `_resolve_security`, the `network_security` filter and the inventory's `network.security`. `network_secrets_store` now follows `secrets.provider`, so `secrets: {provider: files}` turns OpenBao off for a network's secrets. The tests are in `tests/test_security.py` (39 tests): every rule of section 2.4, the presets, and a check that every file in `networks/` resolves to what it did before. `validate-network.yaml` passes on the repository's files, and on a copy with the section 2.1 example. The settings that nothing deploys yet (`administrative_identity`, `pki`, and the openbao host's `tls`, `ssh_user_ca`, `ssh_host_ca` and `pki`) are validated and print a "not deployed yet" warning. Remove each warning in `NOT_DEPLOYED_YET` as its phase lands. The schema is in [networks/README.md](../../networks/README.md#security).

Phase 2 is deployed on `home` (`home.openbao`, VM 120, at https://192.168.1.20:8200) and trusted by `home` and `lab`; `agent-developer` is untouched. What it added:

- [roles/openbao](../../roles/openbao/README.md#ssh-certificates): `tls.yml` (4.2.2), `ssh-ca.yml` (4.2.3), `admins.yml` (4.2.4), the audit log and `admin_sources` in `templates/openbao.nix.j2`, and HTTPS in `configure.yml` and `verify.yml`.
- [roles/nixos_base](../../roles/nixos_base/templates/ssh-trust.nix.j2): `ssh-trust.nix` on every host, imported by `common.nix` (4.2.5). The template build writes an empty one.
- [scripts/ssh-cert](../../scripts/ssh-cert) (4.2.6), the `openbao_ssh_roles`, `openbao_ssh_admin_roles` and `ssh_trust_principals` filters, the trusted-CA check in [network_verify](../../roles/network_verify/tasks/main.yml), and more tests in `tests/test_security.py`.

Live checks (4.2.7), run with two throwaway admins on `home` (nats, ws) and on `lab` (its router and webserver-lab, deployed for this), through OpenBao's API with `curl`:

1. Certificates log in as the user their principal is for: `home-admin` as `admin` on nats and ws, `home-operator` as `dev` on ws (no sudo), `lab-admin` on the lab router and, through it with `ssh -J`, on webserver-lab. sshd logs the key ID (`userpass-<admin>-<role>`).
2. Refused: `home-admin` on lab, `lab-admin` on home, an admin certificate as `dev`, an operator one as `admin`, an operator certificate as a jump, the key without a certificate.
3. A 5-second certificate stops working when it expires; a session opened with it stays open.
4. No certificate for a role the admin doesn't have, for another principal than the role's, or for more than 24h. With `mfa: true`: no token without a code or with a wrong one; with the right one, the admin's policy. With `mfa: false`, the password alone.
5. With OpenBao stopped, an existing certificate still logs in and `deploy-host` of nats still works. Its redeploy unseals it.
6. Ansible deploys with its static key throughout.
7. `verify-network` on home and lab reports each host's CA as the network's.

Differences from the plan, found while building it: admin certificates allow port forwarding (4.2.3); the audit log is configured, not enabled through the API (4.2.1); `userpass` can't make a login without a password, so new logins are made by hand with the root token and the deploy gives them their policies; TOTP enrolment uses the root token's `admin-generate`, since an admin with MFA on can't log in to enrol. **Not checked:** running `scripts/ssh-cert` itself, which needs the `bao` CLI on the desktop. Its `--list` and `--config` work; signing was checked with the same API calls through `curl`.

Phase 2b is deployed on `home` (openbao, nats, ws):

- **Own host keys** ([identity.yml](../../roles/nixos_base/tasks/identity.yml)): after the MAC check, a VM whose `/etc/ssh/nixlab-host-keys-vm` doesn't hold its VM ID gets new ed25519 and RSA host keys, sshd is restarted with them (the old ones come back if it doesn't start), and this machine's `known_hosts` entry for its address is replaced. That marker, rather than comparing with the template's fingerprint as 4.3 planned, needs no fingerprint in `proxmox/vars.yaml` and also covers VMs deployed before this change.
- **Host CA** ([ssh-host-roles.yml](../../roles/openbao/tasks/ssh-host-roles.yml)): `ssh-host-signer/` with one role per network, `hosts-<network>`, allowed only that network's hosts' names and addresses (`openbao_ssh_host_roles`). `ssh-ca.yml` is now shared by both CAs; the user CA's roles moved to `ssh-user-roles.yml`.
- **Host certificates** ([host-cert.yml](../../roles/nixos_base/tasks/host-cert.yml)): signed for a year, kept while they match the key, CA and names with 30 days left, `HostCertificate` in `ssh-trust.nix`. `scripts/ssh-cert --trust-hosts` prints the `@cert-authority` lines; `network_verify` checks the certificate.
- **Checked live:** each VM reported a new host key; with only the `@cert-authority` line in `known_hosts` and `StrictHostKeyChecking=yes`, all three hosts are accepted and without it refused; nats's certificate is refused when presented as ws ("name is not a listed principal"); a redeploy keeps the certificate and the keys; `verify-network` on home is clean.

## 1. Where things stand

| Area | Today | What's missing |
|---|---|---|
| Admin SSH | Every VM's `admin` user has one key, `NIXOS_DEPLOYMENT_PUBLIC_KEY` ([common.nix](../../modules/common.nix)). Ansible and people both use it. Workstation users have their own `ssh_key_files`. | No CA, no short-lived credentials, no difference between Ansible and a person, no per-network roles. |
| SSH host keys | Every clone has the template's host key. Deploys use `StrictHostKeyChecking=accept-new`, and a MAC check ([identity.yml](../../roles/nixos_base/tasks/identity.yml)) makes sure the right VM is being changed. | Host keys can't identify a VM, so host certificates can't either until each VM has its own key. |
| Network secrets | Done by [OPENBAO-SECRETS.md](OPENBAO-SECRETS.md): a network with an `openbao` host keeps its hosts' secrets at `<network>/<host>`. The deploy reads them with the root token, over plain HTTP. | No narrower token, no TLS, no backups, no runtime access for VMs. |
| Home OpenBao | None. [home.yaml](../../networks/home.yaml) has `nats` and `ws` only. | The whole central authority. |
| TLS | Each `proxy` host runs Caddy's internal CA (`tls internal`). Its root is copied to `secrets/<network>/<proxy>-ca.crt`, one per network, and you trust each one. OpenBao itself listens on plain HTTP. | One root, intermediates per network, TLS on OpenBao. |
| Recovery material | `secrets/<network>/<openbao>-init.json` on this machine only. The README asks you to back it up. | Backups of OpenBao's data, and a rule that destroying a network never deletes them. |
| Choosing a strategy | Implicit: if a network has an `openbao` host, its secrets go there. | A declared choice, with checks. |

Two facts the plan depends on:

- **Isolated hosts can't reach the home LAN.** Every router's `blocked_networks` covers `192.168.0.0/16`. The plan keeps that rule: trust reaches isolated hosts as files written by Ansible, not through connections they make (section 3).
- **This machine holds every network's root token and unseal keys** in `secrets/`. Network isolation protects networks from each other's workloads, not from someone who controls this machine. Section 6 covers what follows from that.

## 2. Target configuration

### 2.1 Examples

```yaml
# networks/home.yaml
network:
  name: home
  type: home
  ...
  security:
    strategy: centralized
    administrative_identity:
      instance: home.openbao
    secrets:
      provider: files          # decision 10: keep home's secrets out of the CA instance

hosts:
  - name: openbao
    type: openbao
    vm_id: 120
    ip: 192.168.1.20
    data_disk: {size_gb: 10, storage: local-lvm}
    settings:
      tls: self-signed         # phase 2; from the home intermediate in phase 4
      ssh_user_ca: true        # this instance signs administrators' certificates
      ssh_host_ca: false       # phase 2b
      admin_sources: [192.168.1.0/24] # who may reach port 8200; narrow it to the desktop (decision 12)
```

```yaml
# networks/agent-developer.yaml
network:
  name: agent-developer
  type: isolated
  ...
  security:
    strategy: centralized-local
    administrative_identity:
      instance: home.openbao
    secrets:
      instance: agent-developer.openbao
    pki:                                # phase 4
      provider: openbao
      instance: agent-developer.openbao
```

```yaml
# networks/lab.yaml: no security: block. Same as strategy: current.
```

### 2.2 What an instance provides and what a network uses

The design's example sets `ssh_user_ca: true` under a network's `administrative_identity`. That means "hosts the CA" in one place and "trusts the CA" in another. The plan splits the two:

- **An `openbao` host's `settings:` say what it provides:** `ssh_user_ca`, `ssh_host_ca`, `pki`, `tls`.
- **A network's `security:` says what it uses**, by naming an instance as `<network>.<host>` ([decision 14](../ARCHITECTURE.md#11-architectural-decisions) of the architecture).

### 2.3 `network.security`

| Setting | Values | Meaning |
|---|---|---|
| `strategy` | `current` (default), `centralized`, `centralized-local`, `independent` | A preset that fills in the three settings below. Anything set below overrides it. |
| `administrative_identity.provider` | `keys`, `openbao` | `keys`: only static `authorized_keys`, as today. `openbao`: hosts also trust the SSH user CA of `instance`. |
| `administrative_identity.instance` | `<network>.<host>` | An `openbao` host with `ssh_user_ca: true`, on this network or on a network of type `home`. |
| `administrative_identity.ssh_host_ca` | `true`, `false` (default) | Phase 2b: this network's hosts get host certificates from `instance`, which must have `ssh_host_ca: true`. |
| `administrative_identity.principals` | map of local user to principals | Optional. Defaults in section 4.2.5. |
| `secrets.provider` | `files`, `openbao` | Where the deploys keep this network's hosts' secrets. |
| `secrets.instance` | `<network>.<host>` | Must be on **this** network. |
| `pki.provider` | `proxy-internal` (default), `openbao` | Who issues TLS certificates for this network's services. `proxy-internal` is Caddy's internal CA, as today. |
| `pki.instance` | `<network>.<host>` | Must be on this network, and have `pki` set (phase 4). |

The presets:

| `strategy` | `administrative_identity` | `secrets` | `pki` |
|---|---|---|---|
| `current` | `keys` | the network's own `openbao` host if it has one, else `files` (today's rule) | `proxy-internal` |
| `centralized` | `openbao`, `instance` required | as `current` | `proxy-internal` |
| `centralized-local` | `openbao`, `instance` required | `openbao`, the network's own host (required) | `proxy-internal` until phase 4 |
| `independent` | `openbao`, the network's own host | `openbao`, the network's own host | `openbao` or `proxy-internal` |

`current` keeps today's rule on purpose. An `openbao` host listed in a network's own file is something the user asked for, and [OPENBAO-SECRETS.md](OPENBAO-SECRETS.md) already made it the secrets store. What `current` must never do is make a network depend on an OpenBao in another file. `secrets: {provider: files}` is the way out for a network that wants an `openbao` host but not this rule, such as home in 2.1.

### 2.4 Validation

`validate-network.yaml` and every deploy stop on these. Each one is a test in `tests/test_security.py`.

1. Unknown keys under `security:`, or an unknown `strategy` or `provider`.
2. An `instance` that isn't a declared host of type `openbao`.
3. `secrets.instance` or `pki.instance` on another network. No network keeps its secrets or issues its certificates from another network's OpenBao.
4. `administrative_identity.instance` on another network that isn't of type `home`. One isolated network can never depend on another.
5. An `administrative_identity.instance` without `ssh_user_ca: true`, or `ssh_host_ca: true` on a network whose instance doesn't provide it. `pki.instance` without `pki`.
6. `centralized-local` or `independent` without an `openbao` host on the network. `independent` with an `instance` on another network.
7. An instance with `ssh_user_ca: true` that doesn't have `tls` set. Credentials for signing must not cross the LAN in clear.
8. `strategy: current` together with `administrative_identity.provider: openbao`. A preset can be overridden, but not into its opposite: use `centralized`.

A new filter, `network_security(inventory, network)`, returns the resolved settings, the same way `network_secrets_store` does for secrets today. Roles read it and nothing else. `network_secrets_store` uses it, so `secrets: {provider: files}` turns OpenBao off for a network's secrets even when it has an `openbao` host.

## 3. How trust reaches hosts

No managed host ever connects to the home OpenBao. Only this machine and the administrator's desktop do.

```text
desktop ──login (+ TOTP if on), TLS──▶ home OpenBao ──signed cert (up to 24 h)──▶ desktop
                                   │
                    CA public key, fetched by the home OpenBao's deploy
                                   ▼
              secrets/home/openbao-ssh-user-ca.pub  (this machine; not secret)
                                   │
                  written into each host's NixOS config by its deploy
                                   ▼
     home hosts      agent-developer hosts (via the router, as today)      lab hosts (current: nothing)
```

- **The CA public key is a file in `secrets/<network>/<openbao>-ssh-user-ca.pub`**, written by the home OpenBao's deploy, like `<proxy>-ca.crt` is. Other networks' deploys read the file, not OpenBao. Deploying an isolated network then works while the home OpenBao is down.
- **No firewall changes.** Isolated hosts stay blocked from `192.168.0.0/16`.
- **Connectivity is unchanged.** You reach isolated hosts the way you do today: through the router's WAN SSH, a port forward, or the WireGuard VPN. A certificate is accepted only after you have a path to the host.

## 4. Changes by phase

### 4.1 Phase 1: schema and validation

- [plugins/filter/network_config.py](../../plugins/filter/network_config.py): `check_security` in the validator (section 2.4), the presets, and the `network_security` filter. `network_secrets_store` uses `network_security`.
- `tests/test_security.py`: every preset, every override, every rule in 2.4. One test loads every network file in `networks/` and checks that it resolves to exactly what happens today, so a missing block can't change anything.
- [networks/README.md](../../networks/README.md): a `security:` section with the tables from 2.3.
- Nothing is deployed differently. Nothing reads `administrative_identity` or `pki` yet.

### 4.2 Phase 2: central administrative identity

#### 4.2.1 Check the packaged OpenBao

Before writing any role code, check that `pkgs.openbao` in the flake's nixpkgs has what this plan uses. Record the version and the results in this file.

- The SSH secrets engine, signing user and host certificates.
- `userpass` auth, and login MFA with TOTP.
- PKI with an ACME directory (phase 4 depends on it).
- A file audit device.

If login MFA is missing, the `admin_mfa` and `mfa` settings in 4.2.4 are left out until a version has it. Validation then rejects them, and logins use the password only.

**Result (2026-11-21):** nixpkgs on the VMs (NixOS 26.05) has OpenBao 2.6.2. The SSH engine makes ed25519 CA keys; `userpass` works; TOTP methods and login enforcement work; PKI has ACME (`config/acme`). One difference: audit devices can't be enabled through the API in OpenBao 2.x ("use declarative, config-based audit device management"), so the audit log is in OpenBao's configuration file (`audit.file = {type, path, options}`).

#### 4.2.2 TLS for OpenBao

A new `tls` setting on the [openbao](../../roles/openbao/README.md) role, for every `openbao` host:

- `tls: self-signed`: the deploy makes a key and a certificate on the VM, with the host's address and DNS names, valid for 2 years. The key never leaves the VM. The certificate is copied to `secrets/<network>/<openbao>-tls.crt`, like the proxy's CA. The listener then serves HTTPS.
- `tls: none` (the default for now): plain HTTP, as today.
- Phase 4 adds `tls: pki`, a certificate from the network's intermediate.
- `host_secrets`, `verify.yml` and the openbao role's own API calls use `https://` and the certificate file when it is set. The README's `BAO_ADDR` examples get `BAO_CACERT`.

#### 4.2.3 SSH user CA

A new `tasks/ssh-ca.yml` in the openbao role, run when `ssh_user_ca: true`:

1. Mount the SSH engine at `ssh-client-signer/` if it is missing.
2. Make the CA key inside OpenBao (`generate_signing_key=true`) **only if it has none**. The key never leaves OpenBao. A deploy never replaces it. Replacing it needs `-e openbao_ssh_ca_rotate=true` and a second CA key during the changeover (phase 5).
3. Write the public key to `secrets/<network>/<openbao>-ssh-user-ca.pub`. Stop if the file exists with a different key, the same way `-init.json` is guarded.
4. One signing role per network that uses this instance, made from the network files, plus `homelab-admin` for all of them:

   | Role | `allowed_users` (principals) | TTL | Extensions |
   |---|---|---|---|
   | `homelab-admin` | `homelab-admin` | 24 h, max 24 h | `permit-pty`, `permit-port-forwarding` |
   | `<network>-admin` | `<network>-admin` | 24 h, max 24 h | `permit-pty`, `permit-port-forwarding` |
   | `<network>-operator` | `<network>-operator` | 24 h, max 24 h | `permit-pty` |

   `settings.ssh_cert_max_ttl` (default `24h`) sets both. OpenBao refuses anything longer. `scripts/ssh-cert --ttl 2h` asks for a shorter certificate.

   `allow_user_key_ids: false` and `key_id_format: "{{token_display_name}}-{{role_name}}"`, so each certificate's key ID names who asked for it and appears in the hosts' sshd logs. Admin roles allow port forwarding: the live checks found that `ssh -J` through an isolated network's router needs it, and admin certificates give root anyway. Operator roles allow a terminal only, so they can't be used as a jump. No role allows agent forwarding. Roles of networks that no longer use this instance are reported, not deleted.
5. A file audit device at `/var/lib/openbao/audit.log` on the data disk, in OpenBao's configuration file (4.2.1). Every signing is then recorded.

#### 4.2.4 Administrators and their login

On the instance with `ssh_user_ca: true`:

- `settings.admins`: a list of `{name, roles}`, such as `{name: alice, roles: [homelab-admin]}`. No passwords in the network file.
- The deploy makes a `userpass` login and a policy for each one, so that `sign/<role>` works for its roles and nothing else. It writes no password: first-time setup is a manual step in the README (`bao write auth/userpass/users/<name> password=-`), because it's sensitive. The deploy then reports admins who haven't set one yet.
- **MFA is optional** (decision 4). `settings.admin_mfa: false` (the default) means a password is enough. `true` makes every admin also enter a TOTP code. An admin's own `mfa: true` or `mfa: false` overrides it, so you can try MFA on one test admin before turning it on for everyone:

  ```yaml
      settings:
        admin_mfa: false
        admins:
          - {name: alice, roles: [homelab-admin]}
          - {name: alice-mfa, roles: [homelab-admin], mfa: true}   # to try it out
  ```

  When any admin needs MFA, the deploy makes one TOTP method and a login enforcement that applies to those admins' identities only. It enrols nobody. Enrolling is a manual step in the README, which shows the QR code once (`bao write identity/mfa/method/totp/admin-generate ...`). The deploy reports admins who need MFA but haven't enrolled, since they can't log in yet. Turning MFA off for an admin removes them from the enforcement and keeps their enrolment, so turning it back on doesn't need a new QR code.
- Removing an admin from the list disables the login, rather than deleting it.
- The root token is used only by this instance's own deploy, and the README says to keep it off the desktop.

#### 4.2.5 Hosts trust the CA

A new template in [nixos_base](../../roles/nixos_base/tasks/main.yml), `ssh-trust.nix`, built from `network_security`. Every host type gets it, routers included:

```nix
services.openssh.settings = {
  TrustedUserCAKeys = "/etc/ssh/trusted-user-ca.pub";
  AuthorizedPrincipalsFile = "/etc/ssh/auth_principals/%u";
};
environment.etc."ssh/trusted-user-ca.pub".text = "<CA public key>";
environment.etc."ssh/auth_principals/admin".text = "homelab-admin\nagent-developer-admin\n";
environment.etc."ssh/auth_principals/dev".text = "agent-developer-operator\n";   # workstation user
```

- **Default principals:** `admin` accepts `homelab-admin` and `<network>-admin`. A workstation's user accepts `<network>-operator`. `administrative_identity.principals` overrides them.
- **`authorized_keys` still works.** `AuthorizedPrincipalsFile` only applies to certificates, so Ansible's key and the workstation users' `ssh_key_files` keep working (decision 11). That is also the way back in when the home OpenBao is lost.
- **With `keys`** (`current`), the template is empty and sshd is configured exactly as today.
- [network_verify](../../roles/network_verify/README.md) checks that each host's `trusted-user-ca.pub` matches the file in `secrets/`, and that hosts on `keys` networks have none.

#### 4.2.6 Desktop

A script, `scripts/ssh-cert`, run on the desktop:

```bash
scripts/ssh-cert agent-developer-admin [agent-developer-operator ...] [--ttl 2h] [--key ~/.ssh/id_ed25519]
# 1. bao login -method=userpass username=<you>  (password, then a TOTP code if MFA is on for you)
# 2. for each role:
#      bao write -field=signed_key ssh-client-signer/sign/<role> \
#          public_key=@~/.ssh/id_ed25519.pub valid_principals=<role> \
#          > ~/.ssh/nixlab/<role>-cert.pub
# 3. prints each certificate's principals and expiry (ssh-keygen -L),
#    and the ssh command that uses it
```

The private key never leaves the desktop. The script uses `BAO_ADDR` and `BAO_CACERT` from `secrets/home/`. The Bao token it gets is short-lived (`token_ttl` 15 minutes on the userpass mount), and the script revokes it when it is done. Several roles in one run need only one login.

**One certificate file per role.** Each role's certificate goes to its own file in `~/.ssh/nixlab/` (`0700`), named `<role>-cert.pub`, all signed for the same public key. Asking for one role replaces only that role's file, so an admin and an operator certificate can be held at once, each with its own expiry. The script never writes `~/.ssh/id_ed25519-cert.pub`: `ssh` would offer that file to every host, whatever the role.

Each certificate carries one principal. A role that allowed both `-admin` and `-operator` would give one file that logs in as either user, but then every certificate you hold would be root-capable, even when you only meant to be an operator. Per-role files keep being root a deliberate choice (decision 14).

Two ways to use them:

- **One connection:** the command the script prints:
  ```bash
  ssh -i ~/.ssh/id_ed25519 -o IdentitiesOnly=yes \
      -o CertificateFile=~/.ssh/nixlab/agent-developer-admin-cert.pub \
      admin@gitea.agent-developer.home.arpa
  ```
- **Every connection:** `scripts/ssh-cert --config` prints a block for `~/.ssh/config`, one `Host` pattern per network, listing that network's role files and `homelab-admin`'s:
  ```text
  Host *.agent-developer.home.arpa
      IdentityFile ~/.ssh/id_ed25519
      IdentitiesOnly yes
      CertificateFile ~/.ssh/nixlab/agent-developer-admin-cert.pub
      CertificateFile ~/.ssh/nixlab/agent-developer-operator-cert.pub
      CertificateFile ~/.ssh/nixlab/homelab-admin-cert.pub
  ```
  `ssh admin@...` and `ssh dev@...` then just work. `ssh` offers the listed certificates in turn, and the host accepts the one whose principal the user accepts. Missing files are skipped. Expired ones are offered and refused. The script writes nothing to `~/.ssh/config` itself; you paste the block in.

Each certificate offered counts against sshd's `MaxAuthTries` (6). That's why the block sets `IdentitiesOnly yes`, so keys in an SSH agent aren't offered too, and lists only one network's roles. A host needs no change for any of this.

`scripts/ssh-cert --list` shows every file in `~/.ssh/nixlab/` with its principal and expiry, and `--clean` deletes the expired ones.

#### 4.2.7 Live checks

On `home` and `agent-developer`:

1. A certificate for `agent-developer-admin` logs in as `admin` on an agent-developer host, through the router as today. The host's sshd log shows its key ID.
2. The same certificate is refused on a home host and on a `lab` host. `homelab-admin` works on both home and agent-developer.
3. A certificate is refused after it expires (try one made with `--ttl 2m`). An open session stays open. Asking for more than 24 hours is refused.
4. Wrong password, or a role the admin doesn't have: no certificate. For an admin with `mfa: true`: no code or a wrong code, no certificate. The same admin with `mfa: false` logs in with the password only.
5. Stop the home OpenBao. Existing certificates keep working until they expire. `deploy-network -e network=agent-developer` still succeeds, and its workloads keep working.
6. `deploy-network -e network=lab` changes nothing on lab's hosts.
7. Ansible's own deploys still use its static key everywhere.
8. With both an admin and an operator certificate in `~/.ssh/nixlab/` and the `--config` block in place, `ssh admin@dev-workstation...` and `ssh dev@dev-workstation...` both log in, and the host's sshd log shows the matching key ID for each. Getting a new operator certificate leaves the admin certificate's file and expiry unchanged.

### 4.3 Phase 2b: SSH host CA (decision 1)

1. **Each VM gets its own host key.** The deploy compares the VM's host key with the template's (its fingerprint goes in [proxmox/vars.yaml](../../proxmox/vars.yaml)). If they match, it deletes `/etc/ssh/ssh_host_*`, restarts sshd so NixOS makes new keys, and updates this machine's `known_hosts` for the host's names and addresses, as [switch.yml](../../roles/nixos_base/tasks/switch.yml) already does after an address change. The MAC check stays. It runs before this and still protects deploys on hosts that don't have new keys yet.
2. **`ssh-host-signer/` on the instance**, with one role per network that's only allowed the network's host names, `<host>.<domain>` names and addresses.
3. **The deploy signs each host's public key** with a 1-year TTL, renewing it when less than 30 days are left. The certificate goes to `/etc/ssh/ssh_host_ed25519_key-cert.pub`, with `HostCertificate` set. If the home OpenBao is down, the deploy warns and keeps the old certificate.
4. **The desktop trusts it once:** `@cert-authority *.home.arpa,10.*,192.168.1.* <host CA key>` in `~/.ssh/known_hosts`, written by `scripts/ssh-cert --trust-hosts`.
5. Later, Ansible's `StrictHostKeyChecking=accept-new` could become strict checking against the host CA. That's a separate change.

### 4.4 Phase 3: network-local secrets

This builds on [OPENBAO-SECRETS.md](OPENBAO-SECRETS.md) and finishes its phase 5 live checks first.

- **A narrower deploy token** (that plan's "Later"): the openbao deploy writes a `deploy` policy (read and write on `<network>/*`) and a periodic token to `secrets/<network>/<openbao>-deploy-token`. `host_secrets` uses it. Only the openbao host's own deploy uses the root token.
- **TLS** from 4.2.2 for every network's OpenBao, `self-signed` until phase 4.
- **Backups:** a playbook, `playbooks/openbao-backup.yaml -e network=<name>`, makes a raft snapshot to `secrets/<network>/backups/<openbao>-<date>.snap`. The README says to copy it off this machine together with `-init.json`, because a snapshot can't be restored without the unseal keys. `destroy-host` on an `openbao` host makes a snapshot first, and stops if that fails, unless `-e openbao_skip_backup=true`.
- **Destroying never removes secrets.** `destroy-network` and `destroy-host` never delete anything in `secrets/<network>/`. That's true today. A test makes sure it stays true, and the READMEs say so.
- **A read-only token per host**, besides the root token and the deploy token. When `host_secrets` reads a host's secrets from OpenBao, it also makes sure that host has its own token:
  - **Policy `<network>-<host>-read`:** `read` on `<network>/data/<host>` and `<network>/metadata/<host>`, plus `<network>/data/<host>-users` for postgres. The paths are listed exactly, with no globs, so `postgres` can't read `postgres2`. No write, no list, nothing outside the host's own paths.
  - **The token:** periodic (`period` 768h, renewed by every deploy of the host), `-orphan` so that revoking the root or deploy token doesn't revoke it, and with `display_name` `<network>-<host>` so the audit log shows who read what. It is made only if there's none yet, or the one there is was revoked or expired.
  - **Where it's kept:** `secrets/<network>/<host>-read-token` on this machine, gitignored like the rest. Also on the VM as `/etc/openbao/<host>.token`, root-only (`0400`), with `BAO_ADDR` (and `BAO_CACERT` once there's TLS) in `/etc/openbao/env`, so services or a person on the VM can run `bao kv get <network>/<host>` (decision 13). The VM gets a daily systemd timer running `bao token renew`, so the token doesn't expire between deploys.
  - **Lifecycle:** `destroy-host` revokes the host's token, deletes `<host>-read-token`, and leaves the secret alone. Revoking a credential isn't destroying a secret. `-e openbao_rotate_read_tokens=true` replaces every host's token on the network. The openbao host itself gets none.
  - **Checks:** unit tests for the policy built from the host list. Live: the token reads its own host's secret, and gets 403 on another host's secret, on writes, and on `bao kv list <network>/`.
- **Runtime access with AppRole, optional per host type:** for services that should log in for themselves instead of holding a long-lived token. It uses the same `<network>-<host>-read` policy. Only worth doing if a service needs it; the token above covers the rest.
- **Isolation checks** in [network_verify](../../roles/network_verify/README.md): from a host on an isolated network, the home OpenBao's port and other networks' OpenBao ports are blocked. One network's deploy token is refused by another network's OpenBao.
- **Outage check:** with the home OpenBao and all of home's VMs stopped, the agent-developer workloads keep their secrets and keep running.

### 4.5 Phase 4: PKI

- **Offline root (decision 2):** made once on an offline machine with `step` or `openssl`. The key goes on encrypted removable media and never on this machine. `scripts/pki-root` holds the commands, for the first time and for signing intermediates. The root certificate isn't secret, so it is committed as `pki/root.crt`. It uses ECDSA P-384 and is valid for 10 years.
- **An intermediate per network that sets `pki.provider: openbao`** (decision 7), in that network's OpenBao at `pki_int/`. Getting it signed is two explicit steps, because the root key is offline:
  1. `deploy-host ... -e openbao_pki_csr=true` makes the key inside OpenBao and writes the request to `secrets/<network>/<openbao>-pki.csr`.
  2. You sign it with `scripts/pki-root sign` on the offline machine, then `deploy-host ... -e openbao_pki_signed=<file>` imports the certificate.
- **Name constraints:** the root signs each intermediate with permitted DNS names limited to the network's `domain` (such as `agent-developer.home.arpa`) and IP ranges limited to its subnets. A network whose OpenBao is compromised then can't issue certificates that other networks or the home LAN will accept.
- **Roles:** `workload`, for names in the network's domain only, max TTL 30 days.
- **Home intermediate:** the home OpenBao gets one too, for its own listener (`tls: pki`) and any home services.
- **The proxy:** with `pki.provider: openbao`, Caddy gets its certificates through ACME from `https://<openbao>:8200/v1/pki_int/acme/directory` instead of `tls internal`, and renews them itself. Clients trust `pki/root.crt` once, instead of one `<proxy>-ca.crt` per network. Networks on `proxy-internal` don't change. If 4.2.1 found no ACME support, the fallback is that the deploy issues certificates and a systemd timer on the proxy renews them. That fallback needs its own decision.
- **Revocation:** OpenBao serves the intermediate's CRL. A live check revokes a certificate and makes sure clients refuse it.
- OpenBao listeners move from `self-signed` to `pki`.

### 4.6 Phase 5: other strategies and switching

- **`independent`:** the network's own OpenBao has `ssh_user_ca: true`, its hosts trust only that CA, and `scripts/ssh-cert` takes `--instance`. After phase 2 this is mostly configuration. Try it on a copy of [examples/test.yaml](../../networks/examples/test.yaml).
- **Changing `administrative_identity.instance`** happens in two deploys. The first trusts both CA keys (`TrustedUserCAKeys` takes several). The second, run with `-e security_drop_old_ca=true`, removes the old one. The same applies to replacing a CA key (4.2.3).
- **Changing `secrets.provider` from `openbao` to `files`:** the deploy stops when OpenBao has secrets for a host that has no file, and prints the `bao kv get -format=json` command to export them. Switching never loses secrets silently.
- **Changing `pki`:** the proxy keeps serving its old certificates until the new ones are issued. Both roots stay trusted until the old certificates expire.

## 5. Things this changes for existing setups

- **No `security:` block:** nothing changes. A test checks every file in `networks/` (4.1).
- **Switching an existing network needs a redeploy, not a rebuild.** `deploy-host` or `deploy-network` updates each VM in place: `nixos-rebuild switch` writes the CA key and principals files and restarts sshd, which leaves open sessions alone. Services and data disks aren't touched. A host that isn't redeployed keeps its old trust settings.
- **Adding the home OpenBao:** with today's rule, it would import `nats.env`. Section 2.1 sets `secrets: {provider: files}` to prevent that (decision 10).
- **Ansible keeps its static key.** A home OpenBao that's down, sealed or lost never stops deploys, and never locks you out.
- **The desktop needs the `bao` CLI** and `secrets/home/openbao-tls.crt`.
- **`sshd` changes on every host of a network that switches to `openbao`.** A typo in the principals file can only stop certificate logins, never key logins.

## 6. Security notes

- **The home OpenBao is the most valuable target.** Its SSH user CA can sign `homelab-admin`, which every `centralized` network accepts. What limits that: certificates that expire within 24 hours, MFA where it's turned on, one policy per admin, the audit log, no workload secrets on it (decision 10), and port 8200 open only to `admin_sources` (decision 12). `homelab-admin` is optional. A network can override its principals so that only `<network>-admin` is accepted.
- **SSH user certificates aren't revoked.** Expiry is the protection, so a stolen certificate works for up to 24 hours, as long as the thief also has the private key it was issued for. If that happens, the response is to stop the home OpenBao signing and wait out the day, or to replace the CA (phase 5). A `RevokedKeys` list pushed to hosts is in [Later](#9-later), and matters more with 24-hour certificates than with short ones.
- **This machine holds every root token and unseal key.** The design's "recovery material is stored independently" means `-init.json`, the snapshots and the offline root key need copies somewhere other than this machine. The plan documents that, but it can't enforce it.
- **Trust doesn't give connectivity.** No phase changes router rules. Section 4.4's checks show that.

## 7. Decisions

Decisions 1 to 7 are the design's open questions. Decisions 8 to 14 came up while mapping the design to the repository.

| # | Decision | Recommendation or decision | Why |
|---|---|---|---|
| 1 | Does the home OpenBao also run the SSH host CA? | **Decided: yes, as phase 2b**, after each VM has its own host key. | Shared host keys are a gap anyway. Host certificates are only worth having once keys are unique. |
| 2 | How is the offline root kept? | **Decided: by hand**, on encrypted removable media with a script of the commands. No dedicated VM. | A VM on the Proxmox node isn't offline. Signing happens only once per network. |
| 3 | Human identity provider | **Decided: OpenBao `userpass`**, with optional TOTP (decision 4), at first. LDAP (lldap) later, if there are more administrators. | Home has no LDAP host. lldap has no MFA, and depending on it would make the CA depend on another VM. |
| 4 | MFA for every admin certificate? | **Decided: optional**, `admin_mfa: false` by default, with a per-admin `mfa:` override (4.2.4). Needs 4.2.1 to confirm TOTP login MFA. | This is a lab. A password login about once a day, with certificates of up to 24 hours, is enough day to day, and MFA can be tried on one admin first. Admin certificates are root on every host (the `admin` user has passwordless sudo), so turn it on before giving anyone else a `homelab-admin` role. |
| 5 | Direct, VPN or jump host? | **Decided: unchanged:** direct on home. Isolated networks through the router's WAN SSH or the WireGuard VPN. | That's what works today. Certificates don't need a new path. |
| 6 | Unsealing network-local OpenBao | **Decided: Shamir, as today**, keys in `-init.json`. No auto-unseal through the home OpenBao. | Auto-unseal through home would make every isolated network's startup depend on home, against §12.7 of the architecture. |
| 7 | TLS intermediates everywhere? | **Decided: only networks with `pki.provider: openbao`.** | Others keep the proxy's internal CA. Each intermediate needs a manual signing. |
| 8 | Principal names | **Decided:** `homelab-admin`, `<network>-admin`, `<network>-operator`, mapped as in 4.2.5. | One rule, generated from the network files, and it reads well in logs. |
| 9 | Which operations are explicit | **Decided:** Initialization stays automatic, since its guard already exists. Explicit flags for replacing a CA key, intermediate signing, dropping a CA and skipping a backup. | These are the steps that can break trust or lose data. A first initialization can't. |
| 10 | Does the home OpenBao hold home's secrets too? | **Decided: no**, `secrets: files` on home at first. | Keeps the CA instance's tokens and policies few. A separate home OpenBao for secrets can be added later. |
| 11 | Does Ansible use certificates too? | **Decided: no, not now:** it keeps its static key. | That's the way back in, and deploys keep working without the home OpenBao. |
| 12 | Who can reach the home OpenBao | **Decided: a new `admin_sources` setting:** the firewall on the VM opens 8200 only to those addresses. Default: the home network's CIDR, as now. | Home is a flat LAN. Every device there would otherwise reach the CA's login. |
| 13 | Is a host's read-only token also put on the VM? | **Decided: yes**, root-only, with a renewal timer. | The VM already holds its own secrets in its config, so the token gives it nothing new. It's what lets services read their secrets at runtime and stop having them written into config. If the token is only for you, keep it on this machine and skip the timer. |
| 14 | One certificate per role, or one with several principals? | **Decided: one per role**, each in `~/.ssh/nixlab/<role>-cert.pub` (4.2.6). | A certificate that's also an admin one is root everywhere it's accepted. Per-role files keep being root a choice made per connection. |

## 8. Acceptance

The design's acceptance criteria and where each is checked:

| Criterion | Checked by |
|---|---|
| Existing networks keep working with `current` | 4.1's test over `networks/`, 4.2.7 step 6 |
| Strategy configurable per network | `tests/test_security.py` |
| Home OpenBao issues admin SSH certificates | 4.2.7 steps 1 and 4 |
| NixOS hosts validate them | 4.2.7 steps 1 to 3, `network_verify` |
| Access controlled through principals | 4.2.7 step 2 |
| Isolated networks can have their own OpenBao | Done ([OPENBAO-SECRETS.md](OPENBAO-SECRETS.md)), plus phase 3 |
| Workloads get secrets from their own network's authority | Validation rule 3, `host_secrets` |
| A compromised local OpenBao can't reach other networks' secrets | 4.4 isolation checks, phase 4 name constraints |
| Isolated workloads survive a home OpenBao outage | 4.2.7 step 5, 4.4 outage check |
| Removing a network keeps secrets and backups | 4.4 test that destroys never delete `secrets/<network>/` |
| No network-specific playbooks | Everything goes through `deploy-network`, `deploy-host` and the roles. The only new playbook is `openbao-backup.yaml`, and it works for any network |

## 9. Later

- Ansible signing in with certificates, so the static key becomes break-glass only.
- A `RevokedKeys` list pushed to hosts.
- LDAP login for OpenBao, if there are more administrators.
- Strict host key checking for Ansible against the host CA.
- Other secrets providers (design phase 5), behind the same `secrets.provider` setting.
