# Router

A NixOS VM that connects an isolated Proxmox network to the internet. VMs on the isolated bridge get an address by DHCP and can reach the internet through NAT. They can't reach the home LAN or any other private network.

```
internet ── home router 192.168.1.1 ── vmbr0 ── ens18 [router] ens19 ── vmbr1 (isolated) ── LAN VMs
                                                 192.168.1.13   10.1.0.1                     10.1.0.100–199
```

| Setting     | Value                                                    |
| ----------- | -------------------------------------------------------- |
| VM          | 113, `router`                                            |
| WAN         | `ens18` (net0) on `vmbr0`, `192.168.1.13`                |
| LAN         | `ens19` (net1) on `vmbr1`, `10.1.0.1/24`                 |
| DHCP        | `10.1.0.100` – `10.1.0.199`, 12 hour leases              |
| DNS         | The router forwards LAN queries to `1.1.1.1` and `9.9.9.9` |
| Blocked     | `192.168.0.0/16`, `172.16.0.0/12`, `10.0.0.0/8`           |

These values come from `vars.yaml`, except the bridge name, which is `isolated_bridge` in `proxmox/vars.yaml`.

## Files

| File                  | Purpose                                                              |
| --------------------- | -------------------------------------------------------------------- |
| `vars.yaml`           | VM ID, WAN IP, LAN address, DHCP range, DNS servers, blocked networks |
| `configuration.nix`   | NixOS configuration: LAN interface, NAT, firewall, DHCP and DNS      |
| `router-vars.nix.j2`  | Template for `router-vars.nix`, which passes `vars.yaml` values to `configuration.nix` |
| `router.yaml`         | Deploy playbook                                                      |
| `destroy.yaml`        | Deletes the VM                                                       |

The isolated bridge is created by [proxmox/scripts/isolated-bridge.yaml](../../proxmox/scripts/isolated-bridge.yaml).

## How it works

Everything is in `configuration.nix`:

- **Interfaces:** `ens18` keeps the static home-LAN address from `network.nix`, like every other VM. `ens19` gets the LAN address.
- **NAT:** `networking.nat` masquerades LAN traffic leaving through `ens18` and turns on IPv4 forwarding. IPv6 isn't forwarded, so LAN clients have IPv4 only.
- **Forwarding firewall:** `networking.firewall.filterForward` drops forwarded traffic unless a rule accepts it. Rules, in order:
  1. Replies to connections the LAN started are accepted.
  2. LAN traffic to a blocked network is dropped.
  3. Other LAN traffic out through the WAN is accepted.

  Nothing from the WAN side is forwarded into the LAN, so home-LAN machines can't reach LAN VMs either.
- **Firewall on the router itself:** from the LAN, only DHCP (UDP 67), DNS (53) and ping are allowed. SSH is only open on the WAN side.
- **DHCP and DNS:** dnsmasq listens only on `ens19`. It hands out addresses with `10.1.0.1` as gateway and DNS server, and forwards DNS queries to the servers in `vars.yaml`.

The order matters for rule 2. The NixOS NAT module adds its own "accept LAN to WAN" rule, and the home LAN is also reached through the WAN. `configuration.nix` uses `lib.mkBefore` so the drop comes first.

LAN clients can still ping the router's WAN address, `192.168.1.13`, because ping is allowed on every interface. Nothing else on that address answers them.

## Deploying

The NixOS template must exist first (run `./bootstrap.sh` from the repo root). Then, from the repo root:

```bash
source proxmox/.env
ansible-playbook proxmox/scripts/isolated-bridge.yaml   # once
ansible-playbook hosts/router/router.yaml
```

The bridge playbook creates `vmbr1` with no physical port and no IP on the Proxmox host, so the host isn't reachable from the isolated network. The API token needs `Sys.Modify` on `/nodes/com` for it. It stops if:

- `vmbr1` already exists with a port or an IP (it is in use for something else), or
- other network changes are already staged on the node, because applying the bridge would apply them too. Apply or revert them in the Proxmox UI, or re-run with `-e apply_pending=true`.

On a first run the router playbook:

1. Checks the isolated bridge exists.
2. Clones the template into VM 113 and adds net1 on the isolated bridge. The clone boots on the template's IP, `192.168.1.10`.
3. Checks that the LAN card shows up as `ens19`.
4. Installs the NixOS configuration into `/etc/nixos`: `common.nix`, plus `network.nix` and `router-vars.nix` generated from `vars.yaml`, plus `configuration.nix`.
5. Runs `nixos-rebuild build`, then `nixos-rebuild switch`. The VM moves to `192.168.1.13`. A live switch doesn't add the LAN address on its own, because NixOS only sets it when `ens19` appears and `ens19` has been there since boot. The playbook starts that step (`network-addresses-ens19.service`) itself.
6. Checks the LAN address, IP forwarding, dnsmasq and the blocking rule, and that the router can reach the upstream DNS servers over TCP. It doesn't use ping, because the home network drops outbound ping.

Because new clones use the template's IP, deploy one VM at a time.

## Using the isolated network

Attach a VM's network card to `vmbr1` and let it use DHCP. To check isolation from a LAN VM:

```bash
curl -I https://nixos.org                  # works
ping -c 3 192.168.1.1                      # no reply
```

Use the home-LAN tests above, not ping to an internet address, to check the block. The home network drops outbound ping to the internet, so pinging something like `1.1.1.1` fails even when the internet works. Ping to the home gateway does work when nothing blocks it, as it does from the router itself.

To see addresses handed out, on the router:

```bash
cat /var/lib/dnsmasq/dnsmasq.leases
```

To see how many packets the blocking rule has dropped:

```bash
sudo nft list chain inet nixos-fw forward-allow
```

Give LAN VMs that need a fixed address one outside the DHCP range, for example `10.1.0.10`, with gateway and DNS `10.1.0.1`.

## Firewall commands

The firewall is nftables, generated from `configuration.nix`. Run these on the router (`ssh admin@192.168.1.13`).

### Looking at the rules

```bash
sudo nft list ruleset                            # everything
sudo nft list table inet nixos-fw                # the firewall
sudo nft list chain inet nixos-fw input-allow    # what may reach the router itself
sudo nft list chain inet nixos-fw forward-allow  # what may pass through the router
sudo nft list table ip nixos-nat                 # NAT (masquerade, port forwards)
```

Each chain lists its rules in order, and the first one that matches decides. The `input` and `forward` chains accept replies to existing connections first, and send new connections to `input-allow` or `forward-allow`. Anything those don't accept is dropped.

The private-network block has a counter, so you can see whether it has dropped anything:

```bash
sudo nft list chain inet nixos-fw forward-allow | grep "private networks"
```

If `nft list tables` also shows `ip filter` and `ip mangle` tables, those are left over from the template's older iptables firewall. They accept everything and disappear at the next reboot.

### Watching traffic

```bash
sudo journalctl -k -f -g "refused connection"   # new TCP connections to the router that were refused
sudo grep "src=10.1.0." /proc/net/nf_conntrack  # connections from LAN clients, with their NAT
sudo ss -tulpn                                  # services listening on the router
cat /var/lib/dnsmasq/dnsmasq.leases             # DHCP leases
```

Only connections to the router itself are logged as refused. Forwarded traffic dropped by the private-network block isn't logged; check its counter instead.

### Opening a port temporarily

`nixos-firewall-tool` opens a port on the router until you reset it, the router reboots, or a playbook run reloads the firewall:

```bash
sudo nixos-firewall-tool open tcp 8080
sudo nixos-firewall-tool show
sudo nixos-firewall-tool reset
```

The port opens on **every** interface, LAN included. It only covers connections to the router itself, not traffic passing through it.

### Making a change permanent

Rules you change by hand with `nft` are lost at the next reload, and so are ports opened with `nixos-firewall-tool`. To keep a change, edit `configuration.nix` and re-run the playbook. For example:

```nix
# Open a port on the router's WAN side only.
networking.firewall.interfaces.${wan}.allowedTCPPorts = [ 22 8080 ];

# Forward port 8080 on the router's WAN address to a LAN VM.
networking.nat.forwardPorts = [
  { sourcePort = 8080; destination = "10.1.0.10:80"; proto = "tcp"; }
];
```

The forward lets home-LAN machines reach that one LAN service at `192.168.1.13:8080`. It doesn't let the LAN VM start connections to the home LAN: the private-network block still applies to those. A VM receiving a forward needs a fixed address outside the DHCP range.

Keep `22` in the WAN list. The playbook logs in over SSH on the WAN, and the `admin` user has no password, so there is no other way in.

## Making changes

Edit the files here and re-run the playbook. When VM 113 already exists, the playbook updates it in place on its own IP and doesn't re-clone it.

- **LAN address, DHCP range, DNS servers or blocked networks:** change them in `vars.yaml`. If you change the LAN subnet, keep the DHCP range inside it, and don't overlap it with the home LAN.
- **NixOS settings:** edit `configuration.nix`. Leave the values above out of it; they belong in `vars.yaml`.

The playbook refuses to configure VM 113 if it exists under a name other than `router`.

## Linked clone

By default the VM is a linked clone (`router_full_clone: false`). It's created quickly and uses little disk, but Proxmox won't delete the template while the clone exists, so `./bootstrap.sh --force` fails. Set `router_full_clone: true` before the first deploy to make an independent copy instead.

## Removing the router

```bash
source proxmox/.env
ansible-playbook hosts/router/destroy.yaml
```

This permanently deletes VM 113. VMs on the isolated bridge lose DHCP, DNS and internet access until the router is redeployed. The playbook asks you to type `router` to confirm; pass `-e confirm_destroy=router` to skip the prompt.

The isolated bridge stays. To remove it, delete `vmbr1` under System > Network in the Proxmox UI and apply.
