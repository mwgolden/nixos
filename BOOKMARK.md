# Progress bookmark

Progress against [PLAN.md](PLAN.md). The newest entry is at the top.

## Follow-ups done (2026-10-29)

All of Phases 0 to 8 are built and passed your live tests. These follow-ups came after; none has run live yet.

- **Role READMEs rewritten** for [webserver](roles/webserver/README.md), [postgres](roles/postgres/README.md), [gitea](roles/gitea/README.md), [garage](roles/garage/README.md) and [router](roles/router/README.md):
  - The "Moved to network files" notes and their tables of old settings are gone.
  - The text no longer mentions per-host `vars.yaml`, `move-network.yaml`, the old per-host playbooks, or "home or isolated" switches.
  - Each starts with an example host entry, then describes only what that type adds to a deploy. The router README's DNS, VPN, port forward and firewall sections were already current, and are kept.
- **Gitea's address is worked out from the host's entry.** `public_host`, `public_http_port` and `public_ssh_port` default from it, and are now only needed as overrides. In order:
  - A `proxy:` route gives `https://<route>.<domain>/`.
  - Otherwise, an `expose:` entry for `http_port` gives the router's WAN address and its `wan_port`.
  - SSH uses the router's address and `wan_port` when port 22 has an `expose:` entry, otherwise the VM's DNS name (behind a route) or its address.
  - The deploy message now prints the SSH clone URL too.
  - I rendered it for five cases (route, plain, both forwards, route plus SSH forward, override) and checked `gitea.nix`.
- **Bug fixed:** Gitea's deploy message used `router_ip`, which the Gitea role never defined. It would have failed for an isolated Gitea without a route or `public_host`. Gitea now defines it, like postgres and garage do.
- **SSH options in one place.** Placement, `postgres-users.yaml` and the router inventory now use the `nixlab_ssh_args` filter, instead of their own copies of the SSH and ProxyCommand options. The new output is identical to the old, which I checked with an assert.
- **Checks:** 126 unit tests pass, and so does `--syntax-check` on every playbook.

**To try live:** `deploy-host -e network=lab -e host=gitea`. With your current `lab.yaml` (a `git` route, no forwards), the address should still be `https://git.lab.home.arpa/`, with SSH clones at `gitea.lab.home.arpa:22`. Any deploy also exercises the placement change.

## All phases done (2026-10-29, tested live)

Phases 0 to 8 of [PLAN.md](PLAN.md) are built and passed your live tests. The order used:

1. `ansible-playbook playbooks/validate-network.yaml` (after renaming VM 111 to `webserver-lab`).
2. `ansible-playbook playbooks/deploy-network.yaml -e network=lab`, ending with the network checks.
3. `ansible-playbook playbooks/verify-network.yaml -e network=home`.
4. The test network steps below, which cover the proxy, the VPN and lldap.

If a check later fails on something that's fine, the most likely cause is a service listening on a port its type's `ports.yml` doesn't list.

### Test network steps (from the Phase 7 pause)

Phase 8 adds checks at the end of `deploy-network`, from ARCHITECTURE.MD §10. Before that, please try Phases 6 and 7 live. The throwaway test network exercises all of Phase 7 without touching `lab`.

1. In `networks/examples/test.yaml`, check that `wan_ip` 192.168.1.20 is free on your LAN, and uncomment `test-ldap`. Then:
   - add a VPN to `test-router`'s settings, such as `vpn: {cidr: 10.202.0.0/24, peers: [{name: laptop, ip: 10.202.0.2}]}`
   - `cp networks/examples/test.yaml networks/test.yaml`
   - copy `roles/ldap/env.example` to `secrets/test/test-ldap.env` and set the values

2. Deploy it:
   ```bash
   source proxmox/.env
   ansible-playbook playbooks/validate-network.yaml
   ansible-playbook playbooks/deploy-network.yaml -e network=test
   ```

3. **VPN:** run `sudo wg-quick up ./secrets/test/vpn/laptop.conf` from a machine on the home LAN. Then `ping 10.2.0.11` and `dig test-web.test.home.arpa` should work.

4. **Proxy:** trust `secrets/test/test-proxy-ca.crt`. Then `https://web.test.home.arpa/` and `https://users.test.home.arpa/` should load over the VPN without a warning. Log in to lldap as `admin`.

5. **Clean up:** `ansible-playbook playbooks/destroy-network.yaml -e network=test -e remove_bridge=true`, then `rm networks/test.yaml`.

6. **Phase 6 on lab:** `ansible-playbook playbooks/deploy-network.yaml -e network=lab`. Check the DNS check passes, the postgres forward answers, and Proxmox notes show `nixlab-dns:`.

The [Phase 3 to 5 checks](#live-checks-for-phases-3-to-5) also still apply.

## Phase 8: deployment checks (done 2026-10-29, tested live)

- **New role [network_verify](roles/network_verify/README.md):** runs at the end of `deploy-network.yaml` once every host is deployed, and on its own with the new [playbooks/verify-network.yaml](playbooks/verify-network.yaml), which changes nothing.
- **On each VM:**
  - SSH, its `ens18` address and its default gateway.
  - On isolated networks, every DNS record of the network, including proxy routes.
  - A public name resolving, and TCP 443 to `cache.nixos.org`.
  - On isolated hosts, that the home gateway (TCP 53), the Proxmox web interface (8006) and other networks' gateways time out.
  - That no non-loopback TCP listener is outside 22 plus the type's `tasks/ports.yml`.
  - On the proxy, that each route answers over HTTPS without 502 or 504.
- **From your machine:**
  - Each VM exists and is running, with `net0` and a router's `net1` on the right bridges.
  - On isolated networks, that the router's WAN address doesn't answer on any port the hosts listen on but nothing forwards.
  - When external routes exist, that they answer through 443 and internal ones refuse.
- **One report:** all problems for all hosts come together, `ok` otherwise, then one failure if there were any. The checks never stop half-way.
- **New files:**
  - [files/probe.py](roles/network_verify/files/probe.py): TCP and HTTPS probes using only Python's standard library, run on the VMs with Ansible's `script` module and on your machine.
  - `tasks/ports.yml` in every host type role.
  - New filters: `unexpected_listeners`, `blocked_targets`, `network_verify_proxmox`, `unforwarded_ports` and `nixlab_ssh_args`.
- **Docs:** the role README, a paragraph in the main README's deploy section, and the ARCHITECTURE.MD layout.

Checked:
- 126 unit tests pass. The 13 new ones are in `tests/test_verify.py`.
- Every playbook passes `--syntax-check`.
- A sandbox run checked this machine as a stand-in for four VMs, against fake Proxmox data with planted faults. It reported:
  - the wrong bridge on the proxy, the stopped VM, and the reachable "Proxmox" port
  - every wrong address, route and DNS answer, and the unexpected listeners
  - the unreachable external route

  It then failed once with the total. Loopback listeners, including the IPv6 form of 127.0.0.1, were ignored.

Not checked: real VMs. In particular, whether each host type listens only on the ports its `ports.yml` lists.

## Phase 7 follow-up: external proxy routes, gitea behind the proxy (done 2026-10-29, not yet tested live)

- **`external: true` on a proxy route** publishes it outside its isolated network. It's off by default.
  - When any route on a network is external, the router's TCP 443 and 80 are forwarded to the proxy (forwards `<proxy>-https` and `<proxy>-http`).
  - External routes answer anyone who reaches the proxy.
  - Internal routes now refuse (`abort`) connections from outside the network's subnet, its VPN and the proxy's own loopback, so the new forward can't reach them.
  - Validation refuses `external` on home networks, and when the router's TCP 443 or 80 is already used by an `expose:` entry.
- **Proxy's final message:** it marks each route internal or external, and lists the names to point at the router on pfSense.
- **Gitea:** with a proxy route to its web port:
  - Its address is `https://<route>.<domain>/`, with secure login cookies on and the proxy trusted for forwarded client addresses.
  - SSH clone URLs use the VM's own DNS name, since the route's name points at the proxy.
  - Without a route, nothing changes. `COOKIE_SECURE` moved from `configuration.nix` to `gitea.nix`.
- **Inventory:** routes have `external`, and networks have `proxy_internal_sources`.
- **Docs:** an "External routes" section in the proxy README, a "Behind the network's proxy" section in the gitea README, and `networks/README.md`.

Checked:
- 113 unit tests pass, and so do offline validation (including your current `lab.yaml`) and every playbook's syntax check.
- The proxy's and gitea's config files and messages were generated for a lab with an external gitea route, an internal ldap route and a VPN. Gitea on home without a proxy still gives the same file as before.

Not checked: Caddy's `remote_ip` / `abort` behaviour on a real proxy, and Gitea behind it.

## Phase 7, part 3: lldap (done 2026-10-29, not yet tested live)

- **New host type `ldap`:** [roles/ldap](roles/ldap/README.md) runs lldap.
  - Settings: `base_dn`, which defaults to the network's domain as `dc=` parts, plus `ldap_port` (3890) and `http_port` (17170).
  - If the host has a `proxy:` route to its web port, lldap uses that HTTPS name in its links.
- **Secrets:**
  - `secrets/<network>/<host>.env` holds `LLDAP_ADMIN_PASSWORD` and `LLDAP_JWT_SECRET`. Their format is checked before anything changes.
  - They're copied to root-only files in `/var/lib/lldap-secrets` before the switch. lldap reads them as systemd credentials (`LoadCredential`, through `LLDAP_*_FILE`), so they're never in the Nix store.
  - The admin password is reset to the file's value on every start. lldap restarts when a secret changes.
- **Checks:** the `lldap` service is active, `/health` answers, and the LDAP port accepts connections. The final message gives the web address, the LDAP address, the base DN and the admin bind DN.
- **Data:** a SQLite file on the system disk, with no data disk. The README says to back it up.
- **Example:** a commented-out `test-ldap` (VM 904) in `networks/examples/test.yaml`, behind the proxy as `users.test.home.arpa`.
- **Docs:** the role README, `env.example`, and the host type lists in `README.md`, `networks/README.md` and `secrets/README.md`. PLAN.md now says Caddy.

Checked:
- 108 unit tests pass, every playbook passes `--syntax-check`, and offline validation passes.
- `ldap.nix` and the final message were generated for the example host, behind the proxy and without it.

Not checked: the Nix build and lldap on a real VM. The parts most likely to need a fix:
- `services.lldap.environment` passing `%d` through to systemd.
- The lldap module's own checks on how the passwords are set.

`nixos-rebuild build` runs before the switch, so a problem there stops the deploy without changing the VM.

## Phase 7, part 2: WireGuard VPN on the router (done 2026-10-29, not yet tested live)

- **Turned on per router:** with `settings.vpn`, which holds `cidr`, an optional `port` (default 51820) and `endpoint`, and `peers`. Each peer has a `name`, an `ip` and an optional `public_key`. Off when unset, so `lab` doesn't change. `lab.yaml` has a commented example.
- **Keys:**
  - [roles/router/files/wg-keypair.py](roles/router/files/wg-keypair.py) makes key pairs on your machine with Ansible's Python, which has `cryptography`, so `wg` isn't needed there. They go in `secrets/<network>/vpn/`.
  - Existing keys are kept. Peers with their own `public_key` get no generated key.
  - The router's private key is copied to `/var/lib/wireguard/wg0.key` before the switch, so it's never in the Nix store.
- **Router config:**
  - `wg0` gets the subnet's first address, and each peer may use only its own address.
  - UDP on the WAN address is open for the VPN port.
  - On `wg0`, DNS and SSH to the router are open, and forwarding from the VPN to the LAN is allowed. Lab hosts still can't start connections to VPN clients.
  - dnsmasq also listens on `wg0`, without DHCP there.
- **Checks:** after switching, `wg show wg0 public-key / listen-port / peers` must match the router's key, the port and the peer list. Only public values are read.
- **Client files:** `secrets/<network>/vpn/<peer>.conf` holds the peer's address, the router's DNS with the network's domain, and the router's key and endpoint. Only the network and VPN subnets are routed through the tunnel. The final message explains how to connect from outside the home.
- **Postgres:** with `allowed_networks` unset, it now also allows the VPN subnet.
- **Validation:**
  - The VPN subnet can't overlap any network or other VPN.
  - Peer addresses must be in the subnet, and can't be the router's or another peer's.
  - Peer names must be unique and can't be the router's.
  - Public keys must be in WireGuard's format, and the port can't clash with a UDP `expose:` entry.
- **Docs:** a VPN section in the router README, and the files written by deploys in `secrets/README.md`.

Checked:
- 107 unit tests pass. The 12 new ones cover the VPN in the inventory, postgres's networks and validation.
- The key steps ran twice in a sandbox folder. The second run changed nothing, and each public key matches its private key.
- The router's config file was generated with the VPN on and off. Client files were generated for a peer with a generated key and for one with its own.
- Every playbook passes `--syntax-check`.

Not checked: the Nix build, and WireGuard on a real router. That includes the `wireguard-wg0` unit name the error message mentions, and dnsmasq answering on `wg0`.

## Phase 7, part 1: reverse proxy (done 2026-10-29, not yet tested live)

- **New host type `proxy`:** [roles/proxy](roles/proxy/README.md) runs Caddy. Its sites come from the `proxy:` entries of the other hosts on its network, each with a `name` (one DNS label) and a `port`. Each route is served as `https://<name>.<domain>` and passed to `<host ip>:<port>`.
- **HTTPS:**
  - Certificates come from Caddy's own certificate authority (`tls internal`), named `nixlab <network> <proxy>`.
  - After each deploy, the root certificate is copied to `secrets/<network>/<proxy>-ca.crt` for you to trust. The README says how on each system.
  - Rebuilding the proxy VM makes a new authority.
- **DNS:** on an isolated network, the router's DNS server points each route's name at the proxy. Redeploy the router after changing routes. A home network gets no DNS from this project, so the deploy says which names to add on the home router.
- **Internal only:** nothing outside the network reaches the proxy unless it gets its own `expose:` entry.
- **Validation:**
  - Routes need exactly one `proxy` host on their network.
  - Route names are unique, and no route may share a host's name.
  - The proxy and routers can't have `proxy:` entries.
- **Checks:** after switching, the proxy asks Caddy for each route on the VM itself. No HTTPS answer stops the deploy. A 502 is only reported, because the backend may not be deployed yet.
- **Inventory:** each network has `proxy` and `proxy_routes`, and the route names are in `dns_records`.
- **Example network:** [networks/examples/test.yaml](networks/examples/test.yaml) now has `test-proxy` (VM 903, `10.2.0.10`) serving `test-web` as `https://web.test.home.arpa/`. Its comments now say to clean up with `destroy-network.yaml`.
- **Docs:** `networks/README.md`, the main README's list of host types, and the ARCHITECTURE.MD layout, where the type is `proxy` and the VPN is part of the router role.

Checked:
- 95 unit tests pass. The 9 new ones cover routes, DNS and validation.
- Every playbook passes `--syntax-check`.
- The proxy's and router's config files were generated from the example network, and the proxy's messages were shown with each kind of answer.

Not checked: Caddy on a real VM. That includes where Caddy keeps its root certificate; the deploy searches `/var/lib/caddy` for it.

## Phase 6: derived configuration (done 2026-10-29, not yet tested live)

- **Port forwards from `expose:`:**
  - A host on an isolated network lists the ports to forward to it, each with `port` and optionally `wan_port`, `proto` and `name`.
  - The router builds its forwards from every host's entries.
  - The router's `settings.port_forwards` is gone. Validation names its replacement if it's still there.
  - `networks/lab.yaml` now has `expose: [{port: 5432}]` on postgres, which gives the same forward as before.
- **Validation of `expose:`:**
  - Each router port can go to only one host, and TCP 22 on the router is refused.
  - Entries aren't allowed on home networks or on the router itself.
  - The old "lan_ip must be a host" check is gone, because the address is now always the host's own.
- **DNS records:**
  - Networks take an optional `domain`, which must be unique and defaults to `<network>.home.arpa`.
  - The router's dnsmasq answers for every host on its network, as both `<host>` and `<host>.<domain>`.
  - Names in the domain are never forwarded upstream. DHCP clients get the domain as their search domain.
  - The router now includes `dig`, and its deploy checks each name.
  - Home networks have no DNS of their own here, so their names aren't served.
- **Postgres `allowed_networks`:**
  - It takes network names as well as subnets.
  - Left unset, it is the host's own network, plus the upstream network when the host has `expose:` entries.
  - `lab.yaml` no longer lists it, and the result is the same two subnets as before.
- **Messages:** each host type's final message on an isolated network now shows its DNS name. If the host is exposed, it gives the real router address and port; otherwise, the `expose:` entry to add.
- **DNS name in the Proxmox notes:** on an isolated network, each deploy now adds `nixlab-dns: <host>.<domain>` below the address line. On a home network the line is removed, since there's no DNS server there. The notes are written only when something in them changes.
- **Inventory:**
  - Each host now has `dns_name`.
  - Each network now has `domain`, `dns_records` and `port_forwards`, and each host has `expose`.
  - New filters: `host_client_networks` and `network_cidrs`.
- **Docs:**
  - `networks/README.md` covers `domain` and `expose`, and has a "What is derived from the files" table.
  - The router README has a "DNS names" section and a rewritten "Port forwards" section.
  - The postgres, webserver, gitea and garage READMEs show `expose:` instead of the old forward lists.

Checked:
- 86 unit tests pass. The 23 new ones cover the DNS name in the notes, `expose:` validation, the derived forwards, DNS records, the domain setting and postgres's networks.
- Every playbook passes `--syntax-check`, and offline validation passes.
- The router and postgres templates were rendered from the test fixtures. They give the same forward and the same postgres subnets as before, plus the new DNS settings.
- The final message for each host type was rendered for an isolated host, both with and without `expose:`.

Not checked: the Nix build (nix isn't installed here), and the dnsmasq settings and DNS check on a real router.

Changing a host's `expose:` changes the router's configuration, so redeploy the router afterwards; `deploy-network` deploys it first anyway. Gitea's `public_host` and `public_*_port` settings could also be worked out from `expose:`. That was left out for now.

## Live checks for Phases 3 to 5

```bash
ansible-playbook playbooks/deploy-network.yaml -e network=home   # webserver, gitea (garage is commented out)
ansible-playbook playbooks/postgres-users.yaml -e network=lab -e host=postgres
```

1. Run `validate-network.yaml` again. Every deployed VM should now carry `nixlab`, `net-<network>` and `type-<type>` tags, and nothing should be reported as "not yet tagged".
2. To test pruning safely, use the example test network (see Phase 4). Deploy it, remove `test-web` from `networks/test.yaml`, and run `deploy-network.yaml -e network=test`. It should report `test-web` as removed. Then run it with `-e prune=true`, which should delete it. Finally, `destroy-network.yaml -e network=test -e remove_bridge=true` should leave nothing behind.

## Phase 5: ownership and reconciliation (done 2026-10-29, not yet tested live)

- **Tags:** every deploy sets `nixlab`, `net-<network>` and `type-<type>` on its VM, through the Proxmox API. Only those three kinds of tag are replaced; others, like a `backup` tag, are kept. VMs deployed before this are tagged on their next deploy, which is the adopt step from the plan. The name/ID check in `proxmox_vm` still applies first.
- **Deletes need the tags:** `proxmox_vm_remove` has a new `vm_remove_required_tags`, and every delete path passes `[nixlab, net-<network>]`. It also forgets the SSH key of the address recorded in the VM's notes.
- **Orphan report:** a new `network_config` step, `tasks/ownership.yml`, runs in `deploy-network.yaml` before deploying and in `validate-network.yaml` for every network. It reports:
  - VMs removed from the file
  - VMs moved to another file, which are never pruned
  - VMs not yet tagged

  It stops when a removed VM still holds an address that a file gives another host.
- **Pruning:** `deploy-network.yaml -e prune=true` deletes the removed VMs, routers last, before deploying, so their addresses are free. It asks for the network name, or takes `-e confirm_prune=<network>`.
- **[destroy-network.yaml](playbooks/destroy-network.yaml):**
  - Deletes every VM tagged for the network, routers last.
  - Leaves untagged and moved VMs alone.
  - Asks for the network name, or takes `-e confirm_destroy=<network>`.
  - With `-e remove_bridge=true`, also removes an isolated network's bridge, but only if it really is isolated and no VM has a card on it.
- **Bridge removal:** the `isolated_bridge` role has `isolated_bridge_state: absent` (`tasks/remove.yml`), with the same staged-changes guard as creating one.
- **One API step:** [roles/proxmox_vm/tasks/api-set.yml](roles/proxmox_vm/tasks/api-set.yml) is now the single place that writes VM options through the API. It's used for tags and for the address in the notes.
- **New filters, all unit-tested:** `nixlab_tags`, `proxmox_tags_merge`, `proxmox_tags_list`, `network_config_ownership`, `network_config_destroy_order` and `proxmox_bridge_users`.
- **Tests no longer read `networks/`:** they use fixed copies in `tests/fixtures/networks/`. You commented garage out of `networks/home.yaml`, and two tests broke because they read those files directly. The real files are still checked for validity.
- **Docs:** the README has a section, "Which VMs are the project's", and notes that tagging uses `VM.Config.Options`. `networks/README.md` says what validation reports.

Checked:
- 63 unit tests pass, every playbook passes `--syntax-check`, and offline validation passes.
- Sandbox runs, using fake Proxmox modules, a fake API on `127.0.0.1:8006`, and documentation-only addresses:
  - **Removed VM holding postgres's address, no prune:** it was reported, the untagged router was reported, and the run stopped on the conflict with no Proxmox calls.
  - **The same with `prune=true`:** the removed VM was deleted first. Then the router was tagged `backup;nixlab;net-lab;type-router` and deployed.
  - **`destroy-network`:** it deleted postgres, then the router, and left the moved gitea alone. It refused to remove `vmbr1` while an untagged VM was on it, and removed it once that VM was gone. A wrong confirmation was rejected.
  - **`destroy-host` on an untagged VM:** refused, with no calls.

Not checked: anything on real VMs.

## Phase 4: deploying a whole network (done 2026-10-29, not yet tested live)

- [playbooks/deploy-network.yaml](playbooks/deploy-network.yaml) `-e network=<name>`:
  1. Loads and checks every network file, and compares them with Proxmox.
  2. Deploys the network's hosts with the same per-host play as `deploy-host.yaml`, using `serial: 1` and `order: inventory`. On an isolated network the router goes first, then the rest in file order.
  3. Uses `any_errors_fatal`, so the first failure stops the run. Later hosts may depend on earlier ones.
  4. Ends with one line per host: its address and bridge, and the router it is reached through.

  Hosts removed from a file are not deleted. That belongs to Phase 5.
- The order comes from the `network_config_deploy_order` filter, which is unit-tested.
- The new [isolated_bridge](roles/isolated_bridge/tasks/main.yml) role is built from `proxmox/scripts/isolated-bridge.yaml`:
  - It takes the bridge name as a parameter.
  - An existing bridge is checked to be isolated and otherwise left alone. The old script applied the node's network configuration on every run; the role only applies it when it creates the bridge.
  - It still refuses when someone else has staged network changes, unless `-e isolated_bridge_apply_pending=true` is given.
- The router's `prepare.yml` now runs that role for its LAN bridge, so deploying a router on a new network creates its bridge. `proxmox/scripts/isolated-bridge.yaml` is now a thin wrapper that takes `-e bridge=<name>`, defaulting to `isolated_bridge` in `proxmox/vars.yaml`.
- Already done in Phase 3: the router reads its LAN, DHCP, WAN and blocked ranges from the network file, and SSH goes through each network's own router.
- New [networks/examples/test.yaml](networks/examples/test.yaml): a throwaway isolated network with `test-router` (VM 901) and `test-web` (VM 902) on `vmbr2`, at `10.2.0.0/24`. Validation and deploys don't read `networks/examples/`. To use it, pick a free home-LAN address for the router's `wan_ip` first, then copy the file into `networks/`. A unit test checks it validates next to the real files.
- Docs: the README covers `deploy-network.yaml` and bridge creation. `networks/README.md` covers the examples folder; I removed its stale Phase 2 transition note. I fixed the router README's line on where its settings come from.

Checked:
- 54 unit tests pass, and every playbook passes `--syntax-check`.
- I ran `deploy-network -e network=lab` in the sandbox: fake Proxmox modules, a node without `vmbr1`, and only documentation-only addresses. Results:
  - The order was router, then postgres.
  - `vmbr1` was staged and applied.
  - The router was cloned with `net1` and looked for at the template address.
  - When nothing answered, the run stopped before postgres.

Not checked: anything on real VMs.

### Fix after the first live router run (2026-10-29)

The router deploy failed with "Port forward 'postgres' points at 10.1.0.12, which is not a VM on the isolated LAN". Two causes:

1. **The port forward check ran too early.** The router was found at the template IP (`192.168.1.10`), so its `ens19` had no LAN address yet, and the route check runs before the switch. The old `router.yaml` checked in the same place and would have failed on a new router too.
   - Fix: the route check now runs after the switch.
   - Validation already checks before deploying that each `lan_ip` is a host on the network.
2. **The MAC check ran too late.** It was in `nixos_base`, which the router role only includes after its own checks.
   - Fix: it's now in `roles/nixos_base/tasks/identity.yml`, which `host_deploy` runs right after placement, before any host-type task.

## Phase 3: host types as roles, deployed from the network files (done 2026-10-28, not yet tested live)

**Deploying**
- `playbooks/deploy-host.yaml -e network=<net> -e host=<name>` replaces `hosts/<type>/<type>.yaml`.
- The first play loads and checks the network files, then adds the host and every router to the inventory (`network_config` role, `tasks/inventory.yml`).
- The second play runs over those hosts with `serial: 1`, using [roles/host_deploy](roles/host_deploy/tasks/main.yml). That role runs `<type>/prepare` on the workstation, then `proxmox_vm` and placement there too, then `<type>/configure` on the VM, then `<type>/verify` on the workstation. Phase 4 can use the same play for a whole network.
- `playbooks/destroy-host.yaml` replaces the five `destroy.yaml` files. It refuses to delete a router while VMs of its network still exist.
- `playbooks/postgres-users.yaml` replaces `hosts/postgres/users/users.yaml`. The user list is now under postgres's `settings` in `networks/lab.yaml`, and the reference notes on access levels and roles are in [roles/postgres/USERS.md](roles/postgres/USERS.md).

**Host type roles:** `roles/webserver`, `postgres`, `gitea`, `garage` and `router`.
- Each has `defaults/main.yml`, `prepare.yml`, `configure.yml` and `verify.yml`, and keeps its NixOS files in `files/` and `templates/`, moved with `git mv`.
- Defaults map the host's `settings:` onto the old variable names, so the templates and service tasks are unchanged.
- Rendering each role's templates with today's settings gives the same values as before.
- The router's LAN bridge variable is now `router_lan_bridge`, because `proxmox/vars.yaml` already sets `isolated_bridge` and play vars override role defaults.

**Placement (decision 10)**
- The `network_config_inventory` and `placement_candidates` filters, in [plugins/filter/network_config.py](plugins/filter/network_config.py), work out each VM's attachment (a router attaches upstream at its `wan_ip`) and where to look for it, in this order:
  1. The address recorded in its Proxmox notes.
  2. Its declared address.
  3. The template address.
  4. The far side of an interrupted move.
- `switch.yml` writes `nixlab-address: <ip> on <bridge>` into the VM's Proxmox notes through the API, keeping any other lines.
- `nixos_base` stops if the guest's `ens18` MAC doesn't match `net0`.
- Routers behind which nothing answers are skipped, and a clear error says to deploy the router first.

**Secrets:** `secrets/<network>/<host>.env`, gitignored except [secrets/README.md](secrets/README.md).
- I moved your files without reading them: `hosts/gitea/.env` to `secrets/home/gitea.env`, `hosts/postgres/.env` to `secrets/lab/postgres.env`, and `hosts/postgres/users/.env` to `secrets/lab/postgres-users.env`.
- `gitea.env` was readable by everyone, so I set it to owner-only (600).
- The examples are now `roles/<type>/env.example`.

**Removed**
- All of `hosts/`.
- `hosts/move-network.yaml`. Moving a host is now: move its entry to another network file and deploy it.
- `hosts/router/port-forwards.yaml`. Its tests now run in the router's `verify.yml`.
- The transition test `tests/test_networks_match_host_vars.py`.
- The broken `webserver` entry in `flake.nix`.

**Docs**
- [README.md](README.md): the deploy, addressing and moving sections were rewritten.
- Each `roles/<type>/README.md`: commands and paths updated, plus a table at the top mapping old setting names to network file settings.
- Follow-up: the prose of the role READMEs still uses the old setting names in places. The table covers it, but a rewrite would read better.

**Kept as is on purpose:** the marker `managed by hosts/postgres/users (group)` in `users.sql.j2`. Databases set up earlier carry it, and the users playbook relies on it to recognise its groups.

**Checked**
- 51 unit tests pass.
- Every playbook passes `--syntax-check`.
- Sandbox runs in my scratchpad, against fake Proxmox modules and documentation-only addresses:
  - Deploying gitea, an existing VM, got as far as the SSH lookup. Its secrets were read and its 40 GB disk was left alone.
  - Deploying postgres as a new clone cloned it and added a 20 GB disk, then stopped because the router wasn't answering.
  - Deploying the router added `net1` on `vmbr1`, then looked for the VM at its WAN address and at the template address.
  - `destroy-host` refused a wrong confirmation and refused to delete the router while postgres exists. It deleted postgres once the name was confirmed.
- Not checked: the configure and verify steps, which need real VMs.
- A side effect: the sandbox's postgres runs removed the `10.1.0.12` entry from `~/.ssh/known_hosts`. This is harmless, since the next SSH connection accepts the key again.

## Phase 3 decision (2026-10-28)

Each deploy records the VM's current address in Proxmox. Placement finds the VM there, and its bridge says which network to reach it through. Placement also checks that the guest's `ens18` MAC matches `net0` before changing anything, because every clone shares the template's SSH host key. This is recorded in ARCHITECTURE.MD decision 10 and PLAN.md Phase 3. The QEMU guest agent could replace the recorded address later.

## Before Phase 3: live checks

1. Run the Phase 1 checks listed below (each host playbook on its existing VM).
2. Run `ansible-playbook playbooks/validate-network.yaml` with `proxmox/.env` sourced. This is the first check of the network files against the real Proxmox.

## Phase 2: network files and validation (done 2026-10-28)

- [networks/home.yaml](networks/home.yaml) and [networks/lab.yaml](networks/lab.yaml) describe today's five VMs: same IDs, IPs, disks and settings. lab.yaml includes the router's DHCP, DNS, blocked ranges and port forward.
- [networks/README.md](networks/README.md) documents the schema and what validation checks.
- [plugins/filter/network_config.py](plugins/filter/network_config.py) has the checks:
  - In the files: all settings; uniqueness of names, VM IDs, addresses (including the router's WAN IP) and bridges across all networks; overlapping subnets; addresses inside their subnet and not the network or broadcast address; addresses off the gateway, the template IP, reserved addresses and DHCP ranges; one router per isolated network and none on home networks; upstream networks; port forwards, whose targets must be declared hosts.
  - Against Proxmox: the template exists; no declared ID belongs to a VM with a different name; no declared name exists under a different ID; home bridges exist; existing isolated bridges have no ports and no address.

  It's written in Python with the standard `ipaddress` module, so it can be unit-tested, and it reports every problem at once.
- The [network_config](roles/network_config/) role loads `networks/*.yaml`, runs the checks, and sets `network_configs`, plus `network_config` when `-e network_config_name=<name>` is given. Phase 3 and later use this role.
- [playbooks/validate-network.yaml](playbooks/validate-network.yaml) runs the checks and changes nothing. `-e network_config_check_proxmox=false` skips the Proxmox checks.
- `ansible.cfg` now sets `filter_plugins = plugins/filter`.
- Tests: `.venv/bin/python -m unittest discover -s tests`, 39 tests, all passing:
  - `test_network_config.py`: the real files pass, and each rule catches a broken copy.
  - `test_networks_match_host_vars.py`: the network files agree with `hosts/*/vars.yaml` and `proxmox/vars.yaml`. This keeps them in step until Phase 3 retires the old vars files.
- Checked: the offline validation passes on the real files, and a broken copy reports every problem together.

## Phase 1: shared roles, no behavior change (done 2026-10-28, not yet tested live)

New roles in [roles/](roles/):

- [proxmox_vm](roles/proxmox_vm/tasks/main.yml) handles:
  - the environment variable checks
  - VM lookup and the check that its name matches its ID
  - cloning from the template
  - the optional `scsi1` data disk: add, grow, refuse to shrink
  - extra network cards
  - starting the VM

  It sets `proxmox_vm_existing` and `proxmox_vm_new_clone`.
- [proxmox_vm_remove](roles/proxmox_vm_remove/tasks/main.yml) does the guarded delete:
  - checks the typed confirmation
  - checks the VM name matches its ID
  - stops the VM, then deletes it and its disks
  - forgets its SSH host keys
- [nixos_base](roles/nixos_base/):
  - `main.yml` installs `common.nix` and `network.nix`, and formats a data disk if there is one.
  - `placement.yml`, `placement-try.yml` and `switch.yml` were moved here unchanged from `modules/ansible/`, using `git mv` so their history is kept.
- [dotenv](roles/dotenv/tasks/main.yml) reads a `.env` file into `dotenv_values`. It uses the same parsing and quote stripping as before; I tested this with quoted values, `export`, and a missing file.

Playbooks moved onto the roles:

- `webserver.yaml`, `postgres.yaml`, `gitea.yaml` and `garage.yaml` now use `proxmox_vm`, `nixos_base` and `dotenv`. Each host's own checks and service setup are unchanged.
- `router.yaml` now uses `proxmox_vm`, with `net1` passed as an extra card that is still added before the VM starts, and the shared `switch.yml`. To make that work, the router's inventory entry now carries the same `connect`/`final` vars as the other hosts. This removes the router's separate copy of the build/switch/reconnect steps.
- All five `destroy.yaml` files are now a confirmation prompt plus `proxmox_vm_remove`. Prompts and warnings are unchanged.
- `move-network.yaml` and `postgres/users/users.yaml` use the new role paths and `dotenv`.
- `modules/ansible/` is gone. `modules/common.nix` and `modules/network.nix.j2` stay where they were.

Other fixes:

- `ansible.cfg` no longer sets `inventory = localhost,`. Ansible read it as a path list and tried to parse every file in the repo root as an inventory, which made each run take about 23 seconds.

Small differences in order. None of them change the result:

- The environment variable check now runs after the `.env` checks instead of before them.
- In the configure plays, the data disk is formatted after login, as part of `nixos_base`. Before, it was a separate step at the same point.
- The router now forgets its old host key only for new clones, and `switch.yml` also forgets it when the address changes.

Checked:

- `ansible-playbook --syntax-check` passes for every playbook.

Still to do. You need to run these, since I don't touch the live Proxmox:

```bash
source proxmox/.env
ansible-playbook hosts/router/router.yaml
ansible-playbook hosts/webserver/webserver.yaml
ansible-playbook hosts/postgres/postgres.yaml
ansible-playbook hosts/gitea/gitea.yaml
ansible-playbook hosts/garage/garage.yaml
```

On existing VMs, each run should finish with only the usual changes, such as rewritten config files and a `nixos-rebuild switch` that has nothing to do. Nothing should be cloned, no disks added, and no IPs changed.

## Phase 0: decisions and doc (done 2026-10-28)

- [ARCHITECTURE.MD](ARCHITECTURE.MD):
  - Section 11 now lists the approved decisions instead of open questions.
  - Section 6.1 describes host types as roles, and says why.
  - Section 6.4 shows the target layout.
  - Garage replaces MinIO, and PostgreSQL and the web server are listed as services.
- New [ansible.cfg](ansible.cfg): sets `roles_path = roles`, uses only localhost as inventory, and turns off the "no inventory" warnings. Playbooks must be run from the repository root.
- [README.md](README.md): setup now installs `netaddr` and `ansible.utils`, which Phase 2 needs for IP checks. The layout table lists `ansible.cfg` and `roles/`.
- Installed `netaddr` into `.venv`.
