# Plan: a DMZ on an isolated network

This plan adds an optional DMZ to an isolated network. The DMZ is a second bridge behind the same router VM. Public-facing hosts, such as the proxy, go there so that a compromised one can't reach the rest of the lab. [ARCHITECTURE.md §8](../../ARCHITECTURE.md#8-security-requirements) asks for this: "Public-facing services must not receive unrestricted access to other lab hosts." Today an exposed host sits on the same flat LAN as postgres and LDAP.

The decisions in section 3 were approved on 2026-10-30, as recommended. They are recorded in [ARCHITECTURE.md §11](../../ARCHITECTURE.md#11-architectural-decisions) (decision 13).

## Progress

**All phases are done (2026-10-30).** The test network ran live first, including a fix to a YAML quoting error in the router's DMZ rule check. Then `lab` was deployed from scratch with its DMZ on `vmbr4`: the proxy is in the DMZ at `10.1.1.10`, and gitea, webserver-lab and postgres are on the LAN. Every host passed the network checks. From home, the external `git` route answers through the router, the internal `www` route refuses, and the postgres forward is open. Postgres keeps `expose: 5432` on the LAN, as decision 5 allows, and validation warns about it.

Earlier status, for reference:

Checked without Proxmox:

- 168 unit tests pass, 42 of them new in [tests/test_dmz.py](../../../tests/test_dmz.py). `--syntax-check` passes on every playbook.
- `validate-network.yaml` passes with [examples/test.yaml](../../../networks/examples/test.yaml), which now has a DMZ.
- The router's `configuration.nix` was built in the `nixos-lab` container for three cases: no DMZ, a DMZ with DHCP and VPN, and the test network as Ansible renders it. NixOS checks the ruleset with `nft -c` during the build. The forward rules come out in the order in section 2. Without a DMZ they're the same as before.

Differences from the plan below:

- **Proxy internal sources** stay LAN + VPN + loopback. The LAN subnet was already there. The DMZ is left out on purpose, so a DMZ host can't use the proxy's internal routes to get past the DMZ rules.
- **Postgres client networks** get each DMZ rule's source as a `/32`, not the whole DMZ subnet.
- **New filters:** `network_config_warnings` (shown by `network_config`, never fatal) and `reachable_targets` (the network check's "must get through" probes).

**To try live**, on the test network first:

1. `cp networks/examples/test.yaml networks/test.yaml`, and check `wan_ip` 192.168.1.20 is free. The test network uses `vmbr2` and `vmbr3`.
2. `ansible-playbook playbooks/deploy-network.yaml -e network=test`. The router gets `ens20` on `vmbr3`. `test-proxy` goes in the DMZ, and `test-web` stays on the LAN behind it.
3. The network check at the end covers the DMZ probes. Also try `https://web.test.home.arpa/` over the VPN, if you turn it on.
4. `ansible-playbook playbooks/destroy-network.yaml -e network=test -e remove_bridge=true` should remove both bridges.

For Phase 6, pick a free bridge for `lab`'s DMZ. `vmbr2` and `vmbr3` are the test network's, so for example use `vmbr4`.

## 1. Target

```text
Home LAN (vmbr0)
     |
   ens18 WAN  192.168.1.13
 [ router ]
   ens19 LAN  10.1.0.1  ── vmbr1 ── gitea, postgres, ldap, ...
   ens20 DMZ  10.1.1.1  ── vmbr2 ── proxy, webserver
   wg0   VPN  10.201.0.1
```

| From → to | LAN | DMZ | Home / private | Internet | Router |
|---|---|---|---|---|---|
| **LAN** | (same bridge) | allow | drop | allow (NAT) | DHCP, DNS |
| **DMZ** | drop, except derived or declared pinholes | (same bridge) | drop | allow (NAT) | DNS (and DHCP if on) |
| **VPN** | allow | allow | no route | no route | DNS, SSH |
| **WAN** | only `expose:` forwards | only `expose:` forwards | — | — | SSH, WireGuard |

Replies to allowed connections are accepted, as they are now.

## 2. What exists and what has to change

Everything assumes one network has exactly one bridge, subnet and gateway. The router has two cards, and the forward rules know only `lan` and `wan`.

| Area | Today | Change |
|---|---|---|
| Schema ([networks/README.md](../../../networks/README.md)) | `network:` has one `bridge`/`cidr`/`gateway`/`dhcp` | Optional `network.dmz:` block, and `zone: dmz` on hosts |
| Validation ([network_config.py](../../../plugins/filter/network_config.py) `check_network`, `check_host`) | Bridge and subnet uniqueness, host IP in `cidr`, outside DHCP | Same checks for the DMZ's bridge and subnet. A host's IP must be in its zone's subnet. `dmz` only on isolated networks. `zone` not allowed on routers. |
| Inventory (`network_config_inventory`) | `attach` comes from the network. The router's `nics` is `[net1]`. | `attach` comes from the host's zone (bridge, prefix, gateway, nameserver = router's DMZ address). The router gets `net2` on the DMZ bridge. The network gets a `dmz` dict and `dmz_rules`. |
| Bridge ([router prepare.yml](../../../roles/router/tasks/prepare.yml), [isolated_bridge](../../../roles/isolated_bridge/)) | Creates the LAN bridge | Also creates the DMZ bridge. The role already handles any `vmbrN`. |
| Router vars ([router-vars.nix.j2](../../../roles/router/templates/router-vars.nix.j2), [defaults](../../../roles/router/defaults/main.yml)) | LAN, DHCP, VPN, forwards | `dmz = { enable; address; prefixLength; dhcp...; }` and `dmzRules` |
| Router NixOS ([configuration.nix](../../../roles/router/files/configuration.nix)) | `ens19` address, NAT for `ens19`, private-network drop on `ens19`, `wg0 → ens19` accept | `ens20` address. Add `ens20` to `nat.internalInterfaces`. Same private-network drop on `ens20`, preceded by the pinhole accepts. Accept `ens19 → ens20` and `wg0 → ens20`. Firewall `interfaces.ens20` allows DNS (and DHCP when on). dnsmasq on `ens20`, with `no-dhcp-interface` when the DMZ has no range. |
| Rule order | `mkBefore` puts the private-network drop ahead of NAT's "LAN to WAN" accept | `LAN → DMZ` and the pinholes must come **before** the drop, because the DMZ subnet is inside `10.0.0.0/8`. Without that, the LAN can't reach the DMZ. |
| Router deploy ([configure.yml](../../../roles/router/tasks/configure.yml)) | Requires `ens19`, starts `network-addresses-ens19`, checks forwards route via `dev ens19` | The same for `ens20`. A forward's route check accepts `ens19` or `ens20`, depending on the target host's zone. Check the pinhole rules are in `forward-allow`. |
| VPN (`_vpn`, client template) | `allowed_ips` = LAN + VPN | Add the DMZ subnet |
| Proxy ([roles/proxy](../../../roles/proxy/)) | `proxy_internal_sources` = network + VPN + loopback | Unchanged: the network's subnet is the LAN. The DMZ is left out, so DMZ hosts can't use internal routes. |
| Postgres client networks (`host_client_networks`) | Network + VPN + upstream when exposed | Add each DMZ rule's source host as a `/32` |
| Network checks ([network_verify](../../../roles/network_verify/), `blocked_targets`, `network_verify_proxmox`) | Isolation from home, Proxmox and other networks. Router `net1` on the right bridge. | From DMZ hosts: a LAN host on a port with no pinhole must time out. From LAN hosts: a DMZ host must answer. The router's `net2` must be on the DMZ bridge. |
| Teardown ([destroy-network.yaml](../../../playbooks/destroy-network.yaml)) | `remove_bridge=true` removes the network's bridge | Also removes the DMZ bridge, with the same "unused and isolated" guards |
| Tests ([tests/](../../../tests/)) | Fixtures without a DMZ | DMZ fixtures for validation, inventory, placement and verify filters |

Already works and needs no change:

- **Placement.** It moves `net0` to whatever bridge `attach` names. Moving the proxy from `vmbr1` to `vmbr2` is handled like any network move.
- **SSH through the router.** `nixlab_ssh_args` jumps through the router's WAN address, and the router routes to both zones.
- **DNS.** dnsmasq answers for every host in the file. DMZ hosts are added the same way.
- **Port forwards.** NAT `forwardPorts` doesn't care which internal interface the target is on.

## 3. Decisions needing approval

| # | Decision | Recommendation | Alternative |
|---|---|---|---|
| 1 | Where the DMZ is declared | A `dmz:` block inside the isolated network's file. The router stays a single host in a single file, and "exactly one router per isolated network" still holds. | A separate `type: dmz` network file pointing at its parent's router. Per-network code (bridge, attach, DNS) would carry over more easily, but firewall rules and destroy ordering would span two files and the router would belong to two networks. |
| 2 | How hosts join | `zone: dmz` on the host. Default `lan`. | A `hosts_dmz:` list. That's harder to move a host between zones. |
| 3 | DHCP in the DMZ | Off by default, with optional `dmz.dhcp`. Every DMZ host is declared with a fixed IP, and no DHCP means a stray VM on `vmbr2` gets nothing. | Always on, like the LAN |
| 4 | DMZ → LAN pinholes | **Derived** from proxy routes: proxy in DMZ, backend in LAN → allow `proxy_ip → backend_ip:port/tcp`. Plus an explicit `reach:` list on DMZ hosts (`- host: postgres` / `port: 5432`) for anything else. Validation checks the target is a declared LAN host. | Explicit only. Simpler, but the proxy's backends would be listed twice, which goes against [§7](../../ARCHITECTURE.md#7-reverse-proxy-and-service-access). |
| 5 | Exposure policy when a DMZ exists | Validation **warns** when an `expose:` entry or external route targets a LAN host while the network has a DMZ. | Refuse it. That's stricter, but it breaks e.g. postgres's current `expose: 5432` until it's moved or removed. |
| 6 | DNS split | One domain and one dnsmasq for both zones. DMZ hosts can resolve LAN names, but can't connect to them. | Per-zone views. That's more config for little gain. |
| 7 | DMZ → router | DNS only, plus DHCP if it's on. No SSH, like the LAN. | — |

Decision 1 becomes a new entry in [ARCHITECTURE.md §11](../../ARCHITECTURE.md#11-architectural-decisions). §4.1's diagram gets the DMZ bridge.

Proposed schema:

```yaml
network:
  name: lab
  type: isolated
  bridge: vmbr1
  cidr: 10.1.0.0/24
  gateway: 10.1.0.1
  # ...
  dmz:
    bridge: vmbr2
    cidr: 10.1.1.0/24
    gateway: 10.1.1.1        # the router's DMZ address; also the DMZ's DNS server
    # dhcp: { start: 10.1.1.100, end: 10.1.1.199, lease_time: 12h }

hosts:
  - name: proxy
    type: proxy
    zone: dmz
    vm_id: 116
    ip: 10.1.1.10
    # reach:                 # extra DMZ → LAN access, beyond derived proxy backends
    #   - host: ldap
    #     port: 3890
```

## 4. Phases

Each phase can be tested on its own. `lab` keeps working unchanged until a `dmz:` block is added to it. Try each phase on [networks/examples/test.yaml](../../../networks/examples/test.yaml) first.

### Phase 1: Schema, validation, inventory

- Add `dmz` to `NETWORK_KEYS`, and `zone` and `reach` to `HOST_KEYS`. Validate them as described in section 2.
- Inventory: `networks[n].dmz` (`{}` when off), zone-aware `attach`, router `nics` adds `net2`, `allowed_ips` adds the DMZ, `dmz_rules` built from proxy routes and `reach:`.
- Unit tests for each new check and derived value.
- **Test:** `validate-network.yaml` passes on current files, and on `test.yaml` with a DMZ.

### Phase 2: Router with an empty DMZ

- Create the DMZ bridge in `prepare.yml`. Pass `dmz`/`dmzRules` through `router-vars.nix.j2`.
- `configuration.nix`: `ens20`, NAT, forward rules in the order from section 2, input rules, dnsmasq.
- `configure.yml`: require `ens20`, start `network-addresses-ens20`, check its address and the new rules.
- **Test:** deploy the test router with a DMZ and no DMZ hosts. LAN hosts still pass `verify-network`. From the router, `nft list chain inet nixos-fw forward-allow` shows the rules in the right order.
- **Risk:** `net2` is added to a running router. Proxmox hotplugs it (the default hotplug list includes network), but the name must be checked. The new "require `ens20`" assert stops before switching if it came up under another name.

### Phase 3: Hosts in the DMZ

- Move the test proxy (or webserver) to `zone: dmz`. `deploy-network` deploys the router first, so forwards and pinholes point at the new address before the host moves.
- Proxy internal sources and postgres client networks include the extra subnets from section 2.
- **Test:** external routes still answer from home. Internal routes answer from the LAN and the VPN. From the proxy, backends answer and other LAN ports time out.

### Phase 4: Checks

- `network_verify`: the DMZ isolation probes, LAN → DMZ reachability, and the router's `net2` in the Proxmox check.
- **Test:** temporarily remove a derived pinhole and confirm the proxy route check fails. Add an extra `reach:` and confirm the isolation probe for that port is skipped.

### Phase 5: Teardown and docs

- `destroy-network.yaml -e remove_bridge=true` removes the DMZ bridge too, after the hosts and router.
- Update [networks/README.md](../../../networks/README.md) (`dmz`, `zone`, `reach`), [roles/router/README.md](../../../roles/router/README.md) (diagram, rules, DMZ section), [roles/proxy/README.md](../../../roles/proxy/README.md) (proxy in the DMZ), [roles/network_verify/README.md](../../../roles/network_verify/README.md), and [ARCHITECTURE.md](../../ARCHITECTURE.md) §4.1 and §11.
- **Test:** destroy the test network with `remove_bridge=true`. Both bridges are gone, and `vmbr0`/`vmbr1` are untouched.

### Phase 6: Move `lab`

- Add `dmz:` to `networks/lab.yaml`, move `proxy` (and `webserver-lab` if it's public) to `zone: dmz`, and decide what to do with postgres's `expose: 5432` (decision 5).
- Run `deploy-network -e network=lab`. Gitea is reached through the proxy's derived pinhole to port 3000.

## 5. Destructive or risky steps

- **Router redeploy changes the firewall live.** WAN SSH (22) must stay open. It's in `interfaces.ens18` and isn't touched. A mistake in the forward rules can cut the LAN's internet access, but it can't lock out the playbook.
- **Moving a host between zones changes its IP.** Anything pointing at the old address outside the network file (home DNS overrides for external routes, bookmarks) needs updating. The deploy should print the new names and addresses, as it does for external routes now.
- **Bridge creation applies staged Proxmox network changes.** The existing guard (`isolated_bridge_apply_pending`) covers this.
- **No VM is deleted by any phase.** Zone moves reuse the placement code, which moves `net0` and never re-clones.
