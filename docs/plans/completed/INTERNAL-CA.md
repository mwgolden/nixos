# Plan: one certificate authority for every network

Today every network is its own TLS trust domain. Each `proxy` runs Caddy's internal CA, and each OpenBao with `tls: self-signed` makes its own certificate, so your machines trust one file per network:

| File you trust today | Made by |
|---|---|
| `secrets/lab/proxy-ca.crt` | lab's proxy (Caddy `tls internal`) |
| `secrets/agent-developer/web-proxy-ca.crt` | agent-developer's proxy |
| `secrets/workstation-lab/reverse-proxy-ca.crt` | workstation-lab's proxy |
| `secrets/test/test-proxy-ca.crt` | test's proxy |
| `secrets/home/openbao-tls.crt` | home OpenBao's listener (self-signed, also a CA) |

Every new network adds one. Destroying and recreating a proxy makes a new CA, which has to be trusted again. Hosts other than the proxy and OpenBao have no certificates at all.

This plan adds one root CA, kept in the home OpenBao, that issues certificates for hosts on **every** network, home and isolated. You trust the root once, on each of your machines, and never import another certificate. A network opts in with `security.pki`. A network that doesn't keeps working exactly as now.

It is a cut-down replacement for the deferred phase 4 of [NETWORK-SECURITY.md](NETWORK-SECURITY.md#45-phase-4-pki-deferred); [section 3](#3-overlap-with-openbao-and-the-deferred-phase-4) lists exactly what it reuses, changes and drops.

## Progress

**Done (2026-11-21).** Implemented, deployed to `home`, `lab`, `agent-developer` and `workstation-lab`, and checked live: every step under [Live checks](#live-checks) passed, with Firefox and Chrome. Safari wasn't checked. Every decision in [section 9](#9-decisions) was made on 2026-11-21, as recommended.

| Phase | What it delivers | Status |
|---|---|---|
| 0 | Check OpenBao's PKI engine and the browsers on the points below | **done** (results under [Phase 0](#phase-0-checks)); Firefox and Chrome checked live, Safari still to check by hand |
| 1 | Schema and validation for `pki` | **done**: [network_config.py](../../../plugins/filter/network_config.py), tests in `tests/test_security.py` |
| 2 | Root and per-network intermediates in the home OpenBao | **done**: [pki.yml](../../../roles/openbao/tasks/pki.yml), run against a local OpenBao 2.7.3 dev server (root, intermediates, roles, idempotent second run, `openbao_pki_rotate`, the root guard) |
| 3 | Hosts get certificates at deploy, and trust the root | **done**: [tls-cert.yml](../../../roles/nixos_base/tasks/tls-cert.yml), [pki-trust.nix.j2](../../../roles/nixos_base/templates/pki-trust.nix.j2), filters in [pki.py](../../../plugins/filter/pki.py) with tests in `tests/test_pki.py`; run against the dev server with this machine as the VM (new, kept, `pki_renew`, authority down) |
| 4 | The proxy and OpenBao listeners use them | **done**: [proxy.nix.j2](../../../roles/proxy/templates/proxy.nix.j2), [tls.yml](../../../roles/openbao/tasks/tls.yml); templates render and parse with `nix-instantiate --parse` |
| 5 | Switch the repository's networks, docs, retire per-network CA files | **done**: `home`, `lab`, `agent-developer` and `workstation-lab` use `home.openbao`; the example doesn't (see below) |

### Where the implementation differs from the plan

1. **No IP name constraints.** OpenBao (2.7.3 here; the VMs run 2.6.2, to confirm on the first live deploy) only takes `permitted_dns_domains` for the root and intermediates. Addresses are limited when signing instead: each network's `hosts` role has `allowed_ip_sans_cidr` set to its LAN, DMZ, router WAN address and, with an openbao host, `127.0.0.1`. Validation rule 3 (private subnets) was dropped as moot.
2. **CA names have spaces**: `nixlab root on home.openbao`, `nixlab lab intermediate`. OpenSSL checks a CA's own common name against its issuer's name constraints when it looks like a host name, and refused an intermediate named `free`.
3. **Certificates name `<host>.<domain>`, not the bare `<host>`**, which isn't under the network's domain, so neither the role nor the constraints allow it.
4. **`secrets/<network>/<openbao>-tls.crt` stays**, and holds the root with `tls: pki`, rather than no longer being written. `BAO_CACERT`, `host_secrets`, `/etc/openbao/ca.crt` on the VMs and `scripts/ssh-cert` then needed no change.
5. **No `nixlab-tls` group.** The key stays `root:root 0600`; Caddy and OpenBao get it through `LoadCredential`, and the deploy restarts them when it changes (and Caddy whenever the credentials are missing, since a switch only reloads it).
6. **Validation rule 6 (no chains of authorities) was dropped:** a network has only one `pki.instance`, and an authority issuing its own listener's certificate from another root is harmless.
7. **Intermediates are re-signed with fewer than 400 days left** (the plan said a year), so a full one-year certificate always fits under them. The mounts default to the newest issuer after each re-signing (`config/issuers`), and the root truncates rather than refuses near its end.
8. **The example network isn't switched**: the quickstart has no home OpenBao. A commented `security.pki` line shows how.
9. **`verify-network` treats a certificate from an older intermediate as a warning**, not a problem: it still chains to the root. Missing, wrongly named and expired certificates are problems.

### Live checks

Run in this order, since each step needs the one before. All passed on 2026-11-21.

1. **Done (2026-11-21).** `deploy-host -e network=home -e host=openbao`: makes the root and the four intermediates, then moves its own listener to a certificate from the root (one extra restart and unseal). `secrets/home/openbao-pki-root.crt` and `openbao-pki-<network>.crt` appear. Run `openbao-backup.yaml -e network=home` straight after.
2. **Firefox and Chrome done (2026-11-21):** with the root trusted, both accept the home OpenBao's listener certificate (a one-year leaf from `pki-home/`). Trust `secrets/home/openbao-pki-root.crt` on your machines. In Safari (or iOS), check that `https://git.lab.home.arpa/` opens after step 3, and record the result under Phase 0, item 4.
3. **Done (2026-11-21).** `deploy-network` for `home`, `lab`, `agent-developer` and `workstation-lab`. Each host reports a new TLS certificate; each proxy says Caddy's own authority was removed; `verify-network` passes for each.
4. **Done (2026-11-21):** `https://git.lab.home.arpa/` opens with only the root trusted, and the old proxy CA files are gone from `secrets/` (except `test`, whose example network still uses its own). Remove the old `<proxy>-ca.crt` and `openbao-tls.crt` (self-signed) from your machines, and check the sites still open.
5. **Done (2026-11-21).** Redeploy one host: no new certificate. With `-e pki_renew=true`: a new key and certificate.
6. **Done (2026-11-21).** `bao status` with `BAO_CACERT=secrets/home/openbao-tls.crt` (now the root) and `scripts/ssh-cert` still work; agent-developer's hosts still read secrets from its OpenBao, now over HTTPS.

## 1. Goals

1. **Trust one file once.** `secrets/home/openbao-pki-root.crt` on each desktop, laptop and phone. Rebuilding a proxy, a network or an OpenBao never changes it.
2. **Any network.** Home hosts, isolated LANs and DMZs, including networks with no OpenBao of their own.
3. **No new paths between networks.** Isolated hosts still never contact the home LAN; certificates reach them as files written by the deploy, as SSH host certificates already do ([ARCHITECTURE.md §12.3](../../ARCHITECTURE.md#123-administrative-access)).
4. **A compromised network can't fool you about another.** Each network's certificates come from its own intermediate, limited by name constraints to that network's domain and subnets. Private keys of hosts never leave their VM.
5. **Outages don't break deploys.** If the home OpenBao is down or sealed, deploys warn and keep the certificates hosts already have.

Not goals: certificates trusted by the public internet (use Let's Encrypt for anything you publish beyond home), mutual TLS between services, and revocation that clients check (section 8).

## 2. Design

### 2.1 Hierarchy

```text
Home OpenBao (home.openbao)
 ├── ssh-client-signer/        SSH user CA       (exists)
 ├── ssh-host-signer/          SSH host CA       (exists)
 ├── pki/                      Root CA "nixlab root"
 │     ECDSA P-384, 10 years, key generated inside OpenBao, never exported
 │     name constraints: DNS home.arpa (decision 3), IPs 10/8, 172.16/12, 192.168/16
 │
 ├── pki-home/                 Intermediate for home       DNS home.home.arpa, IPs 192.168.1.0/24
 ├── pki-lab/                  Intermediate for lab        DNS lab.home.arpa,  IPs 10.1.0.0/24, 10.1.1.0/24
 ├── pki-agent-developer/      ...                         DNS agent-developer.home.arpa, IPs 10.3.1.0/24, 10.3.2.0/24
 └── pki-<network>/            one per network with security.pki
       P-256, 5 years, signed by pki/, each with one role, "hosts"
          │
          └── leaf certificates, P-256, 1 year (decision 4)
                key made on the VM; only the CSR leaves it
```

The root signs intermediates only. Each intermediate issues leaf certificates for its own network's names: `<host>`, `<host>.<domain>`, the host's addresses, and for a proxy, its route names.

### 2.2 How a host gets a certificate

The same flow as [SSH host certificates](../../../roles/nixos_base/tasks/host-cert.yml), which already works for isolated networks:

1. The host's deploy checks the certificate on the VM. If it exists, chains to the current intermediate, covers the host's current names and has more than 30 days left, it stays.
2. Otherwise the VM makes a key (or keeps its existing one) and a CSR. Only the CSR is read back.
3. **The machine you deploy from** sends the CSR to `home.openbao` at `pki-<network>/sign/hosts`. That machine reaches the home OpenBao directly, and reaches isolated VMs through their router, so the isolated network itself never talks to home.
4. The deploy writes the certificate and the chain to the VM, then reloads whatever uses it.
5. If the home OpenBao can't be reached, the deploy warns and keeps the old certificate, as `host-cert.yml` does.

Files on every VM that has one, for any role to use:

| Path | Mode | Contents |
|---|---|---|
| `/etc/nixlab/tls/key.pem` | `0640 root:nixlab-tls` | the key; never leaves the VM |
| `/etc/nixlab/tls/cert.pem` | `0644` | leaf certificate |
| `/etc/nixlab/tls/fullchain.pem` | `0644` | leaf + intermediate, what servers serve |

Services that need the key are added to the `nixlab-tls` group, or get it through systemd `LoadCredential`, as OpenBao's listener already does.

### 2.3 Who trusts the root

- **Your machines**, once. The deploy of the home OpenBao writes `secrets/home/openbao-pki-root.crt`; how to install it per OS is the same table the [proxy README](../../../roles/proxy/README.md#https) has today, moved to one place.
- **Every VM on a network with `security.pki`**, through `security.pki.certificateFiles` in its NixOS configuration, written by `nixos_base`. Then `curl`, the `bao` CLI, Gitea's webhooks and the like trust hosts on their own network, and `BAO_CACERT` is no longer needed.

### 2.4 Why this shape

- **The root is online, in the home OpenBao**, not offline on removable media. The home OpenBao is already the authority every network trusts for SSH, already backed up by [openbao-backup.yaml](../../../playbooks/openbao-backup.yaml), already TLS and `admin_sources`-limited. An offline root means a signing ceremony per network; that is why phase 4 was deferred. NETWORK-SECURITY.md already named this as the "cheaper middle way".
- **Intermediates live in the home OpenBao too**, not in each network's OpenBao. Then every network can take part, including the three that have no OpenBao, and nothing about issuing depends on a network's own OpenBao being up. A separate intermediate per network still buys name constraints, a separate audit trail and the ability to replace one network's intermediate alone.
- **Leaves are issued at deploy, not by ACME.** ACME would need each host (or a DMZ proxy) to reach an issuer, which means either a path to the home LAN or a DMZ rule into the LAN's OpenBao. Deploy-time issuing needs no new firewall rule. The cost is that renewal needs a deploy; section 2.5 covers that.
- **Caddy doesn't hold an intermediate.** Caddy's own CA could be given an intermediate signed by the root and keep issuing short-lived certificates by itself, but then the proxy, the most exposed host and the one in the DMZ, would hold a key that can sign for its whole network. A leaf key only lets a thief impersonate that proxy.

### 2.5 Renewal

Leaves last a year and are renewed by any deploy of the host when fewer than 30 days are left. Intermediates last 5 years and are re-signed by a deploy of the home OpenBao when less than a year is left; hosts then pick up new certificates on their next deploy, and both chains verify meanwhile because the root doesn't change.

So nothing expires as long as every host is deployed at least once a year. To make that visible:

- `verify-network.yaml` (network_verify) warns about every host whose certificate expires within 30 days, naming the command that renews it.
- `-e pki_renew=true` on a deploy renews regardless of what's left (also used after changing a host's names by hand).

## 3. Overlap with OpenBao and the deferred phase 4

### 3.1 What this reuses

| Existing piece | Used for |
|---|---|
| `security.pki` block, `pki.provider: openbao`, `pki.instance` ([network_config.py](../../../plugins/filter/network_config.py), `network_security`) | The network side. The schema exists and is validated today; only the deferral guards (`PKI_DEFERRED`) block it. |
| The openbao host's `settings.pki` and `tls: pki` | The authority side. Both are accepted by the schema and rejected as deferred; this plan makes them work. |
| `openbao_endpoint` filter, root token from `-init.json`, `ca_path` from `-tls.crt` | How the deploy reaches the home OpenBao, exactly as [host-cert.yml](../../../roles/nixos_base/tasks/host-cert.yml) does. |
| The SSH host CA's per-network signing role `hosts-<network>`, limited to `ssh_host_principals` | The model for `pki-<network>/roles/hosts`, limited to the same names plus proxy routes. A shared filter gives both the same name list. |
| openbao's [tls.yml](../../../roles/openbao/tasks/tls.yml) (key on the VM, renew when 30 days left, restart and unseal on change) | `tls: pki` replaces only the "make a self-signed certificate" step; the rest stays. |
| [openbao-backup.yaml](../../../playbooks/openbao-backup.yaml) raft snapshots | Back up the root and intermediate keys with everything else. Nothing new. |
| `admin_sources` on the home OpenBao | Unchanged; the deploy machine is already in it, since SSH host certificates need the same. |
| The audit log | Every issued certificate is logged, like every signed SSH key. |

### 3.2 What changes in NETWORK-SECURITY.md's decisions

| Item | Was | Now |
|---|---|---|
| Decision 2: offline root | Root on encrypted removable media, `scripts/pki-root` | **Superseded**: root online in the home OpenBao (decision 1 below). |
| Decision 7: intermediates only for `pki.provider: openbao` | Intermediate in **the network's own** OpenBao | Still only for networks that opt in, but the intermediate is in **the home OpenBao**. |
| Validation rule 3: `pki.instance` on another network is rejected | No network issues certificates from another network's OpenBao | `pki.instance` may name an openbao host on the network itself **or on a `home` network**, the same rule administrative identity already has (rule 4). Never another isolated network. |
| Phase 4: Caddy uses ACME from `pki_int/acme/directory` | ACME | Deploy-issued certificate files (section 2.4). |
| Phase 4: `workload` role, 30-day TTL | | One `hosts` role per intermediate, 1-year TTL, renewed at deploy. |
| Phase 4: revocation live check | CRL from the intermediate | Dropped (section 8). |
| ARCHITECTURE §12.2 "Certificate authority hierarchy: deferred" and the TLS column of §12.4 | Offline root, intermediates in network OpenBaos | Rewritten to section 2.1 of this plan. |

### 3.3 What this deliberately doesn't touch

- **Secrets.** `host_secrets`, `<network>/<host>` mounts and the network tokens are unchanged. The home OpenBao still holds no workload secrets (decision 10 of NETWORK-SECURITY.md); a leaf certificate's key is made on the VM, so it never passes through OpenBao.
- **SSH.** User and host CAs stay a separate hierarchy, as §12.2 requires.
- **A network-local OpenBao's own PKI.** The `independent` strategy could later move a network's intermediate into its own OpenBao (section 10). Nothing here precludes it.
- **Isolation rules.** No router or DMZ rule changes.

## 4. Configuration

### 4.1 Examples

```yaml
# networks/home.yaml
network:
  security:
    strategy: centralized
    administrative_identity: {instance: home.openbao, ssh_host_ca: true}
    secrets: {provider: files}
    pki: {provider: openbao, instance: home.openbao}     # new: home's own hosts too

hosts:
  - name: openbao
    type: openbao
    settings:
      tls: pki                     # was self-signed; from pki-home/
      ssh_user_ca: true
      ssh_host_ca: true
      pki: true                    # new: this host is the root and the intermediates
      # or, with the defaults spelled out:
      # pki:
      #   permitted_domains: [home.arpa]
      #   root_ttl: 87600h
      #   intermediate_ttl: 43800h
      #   cert_ttl: 8760h
```

```yaml
# networks/lab.yaml (no OpenBao of its own)
network:
  security:
    strategy: centralized
    administrative_identity: {instance: home.openbao}
    pki: {provider: openbao, instance: home.openbao}
```

### 4.2 Settings

On an `openbao` host, `settings.pki`:

| Key | Default | Meaning |
|---|---|---|
| `permitted_domains` | `[home.arpa]` | The root's DNS name constraint. Every network that uses this root must have its `domain` under one of these. Only read when the root is first made (changing it means a new root; section 7). Decided as `[home.arpa]` (decision 3). |
| `root_ttl` | `87600h` (10 years) | Root lifetime. Only read when the root is made. |
| `intermediate_ttl` | `43800h` (5 years) | Re-signed when less than a year is left. |
| `cert_ttl` | `8760h` (1 year) | Maximum leaf lifetime, set on every `hosts` role. |

`pki: true` means all defaults. `tls: pki` makes the listener's certificate a leaf from its own network's intermediate, which requires the host's network to have `security.pki` pointing at an instance with `pki`.

On a network, `security.pki` keeps its existing meaning: `provider: proxy-internal` (the default, today's behaviour) or `openbao` with an `instance`. No preset turns it on (decision 5).

### 4.3 Validation

Added to `check_security` in [network_config.py](../../../plugins/filter/network_config.py), each with a test in `tests/test_security.py`:

1. `pki.instance` must be an `openbao` host with `settings.pki`, on this network or on a network of type `home` (section 3.2).
2. The network's `domain` must be under one of the instance's `permitted_domains`. Today's domains are all `<name>.home.arpa`, so they pass.
3. The network's subnets (LAN, DMZ, and the router's WAN address if the router gets a certificate) must be in private ranges, so they fit the root's IP constraint.
4. `settings.pki` requires `tls` (`self-signed` or `pki`); issuing requests carry the root token.
5. `tls: pki` on an openbao host whose own network doesn't use a `pki` instance is rejected.
6. A network may not use as `pki.instance` an openbao host that is itself on a network using a different `pki.instance` (no chains of authorities).
7. Remove `PKI_DEFERRED` and the three rejections that use it, and drop `pki` from `NOT_DEPLOYED_YET` as phases land.

## 5. Changes

### 5.1 Home OpenBao ([roles/openbao](../../../roles/openbao/))

New `tasks/pki.yml`, included from `configure.yml` when `settings.pki` is set, after unsealing:

1. **Root:** mount `pki/` (max lease `root_ttl`) if missing. If it has no issuer, `pki/root/generate/internal` with `key_type=ec, key_bits=384`, CN `nixlab root`, `permitted_dns_domains`, the private IP ranges (phase 0 decides how), `max_path_length=1`. Write its certificate to `secrets/home/openbao-pki-root.crt`.
2. **Guard**, like the SSH CA's: if `pki/` has an issuer whose certificate differs from that file (a wiped data disk), stop, and say that hosts would chain to a root no one trusts. Moving the file away accepts the new root.
3. **One intermediate per network that names this instance** (from `network_security` over the whole inventory, as `ssh-host-roles.yml` already does for SSH): mount `pki-<network>/`; `intermediate/generate/internal` (P-256); sign it with `pki/root/sign-intermediate` with the network's `permitted_dns_domains` (its `domain`) and IP ranges (its subnets), `max_path_length=0`; `intermediate/set-signed`. Re-sign when less than a year is left.
4. **One role per intermediate**, `pki-<network>/roles/hosts`: `allowed_domains` = the network's domain, `allow_subdomains`, `allow_bare_domains=false`, `allow_ip_sans`, `server_flag` only, `key_type=ec`, `max_ttl = cert_ttl`, `no_store=false` (so issued certificates are listed and auditable). The exact list of names a host may ask for is enforced on the deploy side by a filter (5.3), and by the role's domain on the OpenBao side.
5. A network removed from the files leaves its `pki-<network>/` mount, like SSH roles; `-e openbao_pki_prune=true` unmounts it after a confirmation. Never part of a routine deploy (NETWORK-SECURITY.md decision 9).
6. Reporting in `verify.yml`: the root's fingerprint, each intermediate's expiry.

`tls.yml` gets a `tls: pki` branch: on the home OpenBao itself, issue from `pki-home/` once step 3 has run. On first deploy the root doesn't exist yet when the listener starts, so the listener starts `self-signed` and switches to `pki` at the end of the same deploy (one restart and unseal). On a network-local OpenBao with `tls: pki`, use 5.2's host flow; `secrets/<network>/<host>-tls.crt` is no longer written, and the README's `BAO_CACERT` lines change to the root.

### 5.2 Every host ([roles/nixos_base](../../../roles/nixos_base/))

New `tasks/tls-cert.yml`, included from `main.yml` when the host's network has `pki.provider: openbao`, beside `host-cert.yml`:

- Check, make the key and CSR on the VM with `openssl` (as `tls.yml` does), sign from localhost with the root token, install, as in section 2.2.
- Sets `nixos_base_tls_cert` (whether the VM has one) and `nixos_base_tls_changed`, for roles that reload a service.
- New `templates/pki-trust.nix.j2`: `security.pki.certificateFiles = [ ./nixlab-root.crt ]`, the root copied next to the configuration. Hosts trust the root even before they have a certificate.

The two cert task files share almost everything (where the CA is, what to do when it's down). Factor the common "reach the home OpenBao from localhost, warn if down" part into one include rather than copying it.

### 5.3 Which names a host gets

A filter `tls_cert_names(vm, inventory)` in [network_config.py](../../../plugins/filter/network_config.py), with tests:

- every host: `<name>.<domain>` and its addresses (LAN or DMZ IP);
- a router: also its WAN address;
- a proxy: also every route's `<route>.<domain>`.

It should share code with `ssh_host_principals`, so that SSH host certificates and TLS certificates name a host the same way.

### 5.4 The proxy ([roles/proxy](../../../roles/proxy/))

With `pki.provider: openbao`, [proxy.nix.j2](../../../roles/proxy/templates/proxy.nix.j2) replaces `tls internal` with `tls /run/credentials/caddy.service/fullchain.pem /run/credentials/caddy.service/key.pem` (via `LoadCredential`, so Caddy's user never reads `/etc/nixlab/tls` directly), drops the `pki { ca local }` block, and stops copying `<proxy>-ca.crt`. `configure.yml` reloads Caddy when `nixos_base_tls_changed`. Its route checks in `verify.yml` verify against the root instead of `-k`. With `proxy-internal`, nothing changes.

### 5.5 Other roles, later and one at a time

Once 5.2 is there, a role can serve TLS by pointing at `/etc/nixlab/tls/`. Candidates, none in this plan's phases: Gitea's own HTTPS, PostgreSQL `ssl = on`, NATS TLS, Grafana, Garage's S3 API. Each would be a `tls: true` setting on that role, valid only when the network uses `pki`.

### 5.6 Docs

- New section "Certificates" in [docs/ARCHITECTURE.md §12.2](../../ARCHITECTURE.md#122-authorities) replacing "deferred", and the TLS column in §12.4.
- [networks/README.md](../../../networks/README.md#security): `pki` is no longer "not deployed yet".
- [roles/openbao/README.md](../../../roles/openbao/README.md): `settings.pki`, `tls: pki`; fix its links to `docs/plans/completed/NETWORK-SECURITY.md`, now under `completed/`.
- [roles/proxy/README.md](../../../roles/proxy/README.md#https): the two modes; the trust table moves to the top-level README.
- [README.md](../../../README.md): Quickstart step 6 and "Reaching lab services from home" trust the root, with a note that networks on `proxy-internal` still have their own file.
- [secrets/README.md](../../../secrets/README.md): `openbao-pki-root.crt`.
- [MOVING-HOSTS.md](../../MOVING-HOSTS.md): a moved host gets a new certificate from its new network's intermediate on its first deploy there (its names changed).

## 6. Phases

### Phase 0: checks

On the home OpenBao (2.6.2 in today's nixpkgs), and in a throwaway mount:

1. `pki/root/generate/internal` with `permitted_dns_domains`. Does OpenBao 2.6 take IP name constraints (`permitted_ip_ranges` or similar) on root generation and on `sign-intermediate`? If not, decide: DNS constraints only, so IP SANs are unconstrained (acceptable for a lab; record it), or no IP SANs in leaves at all.
2. `sign-intermediate` takes `permitted_dns_domains` and `max_path_length`.
3. `sign/<role>` with a CSR from `openssl req -newkey ec` works with `allow_ip_sans` and a `use_csr_sans=false` role (names come from the request body, not the CSR).
4. With the test root trusted in Firefox, Chrome and Safari (or iOS), an intentionally out-of-constraint leaf (`example.com`) is refused, and one for a `lab.home.arpa` name is accepted. Clients that ignore constraints on the root itself still apply the intermediates'. Record the results in this section.
5. A one-year leaf from a user-added root is accepted by Safari and Chrome (the 398-day limit applies only to publicly trusted roots; confirm).

**Results (2026-11-21)**, on a local OpenBao 2.7.3 dev server, with OpenSSL 3, curl, and headless Firefox 153 with an NSS store trusting only the test root:

1. **No IP name constraints**: `root/generate/internal` and `root/sign-intermediate` take `permitted_dns_domains` and `max_path_length`, nothing for IP ranges. Decided: DNS constraints only; IP SANs are limited by each role's `allowed_ip_sans_cidr` when signing.
2. `sign-intermediate` with `permitted_dns_domains=lab.home.arpa`, `max_path_length=0`, `use_csr_values=false` gives a critical name constraint and `pathlen:0`.
3. `sign/<role>` with an `openssl req -newkey ec` CSR, `use_csr_sans=false` and `use_csr_common_name=false` takes names and addresses from the request body only. A name outside the role's domain is refused (`common name example.com not allowed by this role`). Set `allow_localhost=false` and `allow_wildcard_certificates=false`: both default to true. `ca_chain` holds just the intermediate. `/v1/<mount>/ca/pem` answers 204 with no issuer. After `set-signed` on a mount that already has an issuer, the old one stays the default: `config/issuers` needs `default` set to the new one.
4. **Name constraints are enforced**, by OpenSSL/curl and Firefox: a leaf for `example.com`, or for `git.agent-developer.home.arpa`, from lab's intermediate is refused; so is one for `example.com` from an intermediate with no constraints of its own, signed by the constrained root (the root's constraint is enforced too). A `git.lab.home.arpa` leaf is accepted. OpenSSL also checked a CA named `free` against the root's constraint (see item 2 of the differences above). Headless Chrome ignored the test NSS store, so Chrome was checked live instead: it accepts a one-year leaf from the real root (2026-11-21). Whether Chrome refuses an out-of-constraint leaf wasn't tested; the intermediates' own constraints cover clients that might not apply the root's. **Safari is still to be checked by hand** (Live checks, step 2).
5. A one-year leaf is accepted by curl and Firefox, and by Firefox and Chrome live: the home OpenBao's listener, after trusting the real root (2026-11-21). Safari: with step 4.

### Phase 1: schema and validation

Section 4.3 in `network_config.py` and its tests; `tls_cert_names` with tests. `validate-network.yaml` passes on the repository's files, with `pki` still warning "not deployed yet".

### Phase 2: the authority

`pki.yml` (5.1) on the home OpenBao, with `pki: true` in home.yaml and `security.pki` on no network yet: the root and `secrets/home/openbao-pki-root.crt` appear; redeploy is a no-op. Then add `security.pki` to `test` (copy of the example): `pki-test/` appears with the right constraints (`openssl x509 -text` on the intermediate).

### Phase 3: hosts

`tls-cert.yml` and `pki-trust.nix.j2` (5.2). Live on `test`:

1. Deploy: the webserver and the proxy have `/etc/nixlab/tls/` with the expected names. No service serves them yet, so check them with `openssl verify -CAfile openbao-pki-root.crt -untrusted fullchain.pem cert.pem`.
2. Redeploy: no new certificates. `-e pki_renew=true`: new ones.
3. Seal the home OpenBao and redeploy one host: a warning, the certificate stays, the deploy succeeds.
4. From the test webserver, `curl https://openbao.home.home.arpa:8200` fails (isolation unchanged), and the network_verify checks pass.

### Phase 4: services

The proxy (5.4) and `tls: pki` on OpenBao listeners (5.1). Live:

1. On `test`, with only `openbao-pki-root.crt` trusted on your desktop (remove `test-proxy-ca.crt`), `https://web.test.home.arpa/` opens without a warning.
2. Home OpenBao with `tls: pki`: `bao status` works with `BAO_CACERT=secrets/home/openbao-pki-root.crt`, `scripts/ssh-cert` still works.
3. Network-local OpenBao (agent-developer) with `tls: pki`: other hosts' deploys reach it, and the read-only token timers on VMs still work, with no `BAO_CACERT` in `/etc/openbao/env` (the system store has the root).

### Phase 5: switch over

Add `security.pki` to `lab`, `agent-developer`, `workstation-lab` and the example, and `tls: pki` to both OpenBaos; deploy each network; remove the old proxy CAs from your machines. Docs (5.6). Full unit suite and `--syntax-check` on every playbook.

## 7. Things this changes for existing setups

- **No `security.pki` on a network:** nothing changes.
- **Switching a network:** one `deploy-network`. The proxy serves the new certificate as soon as it's deployed, so a client that trusts only the old proxy CA sees a warning until it trusts the root. Trust the root first, then switch.
- **Old proxy CA files** stay in `secrets/` and stay trusted on your machines until you remove them. They can't issue anything new once Caddy stops using its internal CA, but its key is still on the proxy's disk in `/var/lib/caddy`; the switch deletes Caddy's `pki/authorities/local` (decision 6).
- **Losing the home OpenBao** without a backup means a new root: every machine trusts a new file once, and every network is redeployed. Restoring a snapshot ([openbao-backup.yaml](../../../playbooks/openbao-backup.yaml)) avoids that, so a backup after phase 2 is part of the phase.
- **Changing a network's `domain`, or a host's address:** the next deploy of that host gets a certificate for the new names (the check in 2.2 compares names). Changing `permitted_domains` to admit a domain outside `home.arpa` needs a new root.
- **The home OpenBao's listener certificate changes** from self-signed to the root's chain: `BAO_CACERT` in your shell and `scripts/ssh-cert` move to `openbao-pki-root.crt`. During one transition deploy both files work.

## 8. Security notes

- **The home OpenBao now also mints TLS certificates for every opted-in network.** Someone with its root token can issue a certificate for any `home.arpa` name your browser will accept. That is a smaller step than it sounds: the same token already signs `homelab-admin` SSH certificates, which are root on every host. The root's name constraint keeps the blast radius off the real internet: even a stolen root can't impersonate your bank to a constraint-enforcing browser. This is the main reason for decision 3.
- **The deploy uses the root token**, as SSH host signing does. A narrower `pki-issuer` policy and token (sign on `pki-*/sign/hosts` only) is in section 10, together with the same change for SSH host signing.
- **No revocation clients check.** Browsers mostly don't check CRLs or OCSP for private roots, and isolated hosts couldn't reach home to fetch them. If a host's key leaks, `-e pki_renew=true` gives it a new one, and `bao write pki-<network>/revoke` records the revocation in the audit trail; the old certificate stays usable to someone holding its key until it expires. For a network you no longer trust, replace its intermediate (`-e openbao_pki_rotate=<network>`, explicit) and redeploy it; its old leaves still chain to the root until they expire, so a one-year leaf is the exposure window. That window is the main argument for a shorter `cert_ttl` (decision 4).
- **Intermediate keys never leave OpenBao, leaf keys never leave their VM.** The deploy machine sees only CSRs and certificates.
- **Trust doesn't give connectivity.** No router rule changes. A certificate for `git.lab.home.arpa` doesn't make it reachable from anywhere it wasn't.

## 9. Decisions

| # | Decision | Decided (2026-11-21) | Why |
|---|---|---|---|
| 1 | Where the root's key lives | **Decided: online, in the home OpenBao, never exported.** | No signing ceremony per network; backed up with the snapshots. An offline root protects against a compromised home OpenBao, but that OpenBao already holds the SSH CAs that are worth more. |
| 2 | Where each network's intermediate lives | **Decided: in the home OpenBao, one mount per network.** | Works for networks without an OpenBao, and keeps issuing independent of network-local OpenBaos. Moving one into its network's OpenBao is a later option for `independent` networks. |
| 3 | Name-constrain the root | **Decided: yes, DNS `home.arpa` and the private IP ranges.** | It's what makes trusting a homemade root in your everyday browser reasonable. Cost: a domain outside `home.arpa` (a real domain you own, say) needs either a root made with it in `permitted_domains` from the start, or a new root. The list is `[home.arpa]`; a real domain would need a new root. |
| 4 | Leaf lifetime | **Decided: 1 year, renewed at deploy with 30 days left**, plus the verify warning. | Matches SSH host certificates, and deploys are irregular in a lab. Shorter (90 days) shrinks the exposure window in section 8 but means certificates lapse on networks you don't touch for a season. |
| 5 | Does a strategy preset turn `pki` on? | **Decided: no; each network sets `security.pki`.** | Turning it on changes what the proxy serves, which needs the root trusted first. Revisit once every network in the repository uses it. |
| 6 | When a proxy switches, delete Caddy's internal CA? | **Decided: yes**, in the same deploy, with a message. | Leaving a working CA key on a DMZ host, which your machines may still trust, is the thing to avoid. Removing the old file from your machines is still manual. |
| 7 | Home hosts | **Decided: same flow as isolated hosts** (deploy-issued), not ACME or a renewal timer. | One mechanism. Home hosts could reach the home OpenBao and renew themselves; that's in section 10. |
| 8 | Root and intermediate key types | **Decided: root P-384, intermediates and leaves P-256.** | Supported by every browser and by Caddy, OpenBao and openssl. RSA isn't needed for anything here. |

## 10. Later

- **A narrower issuing token:** a `pki-issuer` policy (update on `pki-*/sign/hosts`) and a periodic token in `secrets/home/openbao-pki-token`, used by both TLS and SSH host signing, so deploys stop sending the home root token.
- **Self-renewal on home:** home hosts can reach the home OpenBao, so a systemd timer with a per-host AppRole could renew certificates there without a deploy.
- **ACME from the home OpenBao** for things that aren't hosts of this project (a NAS, the Proxmox UI, the home router), using `pki-home/acme/directory`. The root and the home intermediate are already what they'd need.
- **TLS on other services** (5.5), one role at a time.
- **An intermediate in a network's own OpenBao** for `independent` networks: the CSR comes from the network's OpenBao, the home root signs it through the deploy machine. The name constraints are the same.
- **Trusting the root on your machines automatically:** a `scripts/trust-root` for Linux and macOS, or a NixOS module for NixOS desktops.
