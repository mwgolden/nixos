# Router

A NixOS VM that connects an isolated Proxmox network to the internet. VMs on the isolated bridge reach the internet through NAT, but not the home LAN or any other private network. The router also runs the network's DHCP and DNS, its [port forwards](#port-forwards) and, optionally, a [DMZ](#dmz) and a [VPN](#vpn).

```
internet ── home router 192.168.1.1 ── vmbr0 ── ens18 [router] ens19 ── vmbr1 (isolated) ── LAN VMs
                                                 192.168.1.13   10.1.0.1                     10.1.0.100–199
```

An isolated network has exactly one router, listed in its network file:

```yaml
network:
  name: lab
  type: isolated
  bridge: vmbr1            # created by the router's deploy if missing
  cidr: 10.1.0.0/24
  gateway: 10.1.0.1
  nameserver: 10.1.0.1
  upstream: home           # the network the WAN side is on
  dhcp:
    start: 10.1.0.100
    end: 10.1.0.199
    lease_time: 12h

hosts:
  - name: router
    type: router
    vm_id: 113
    ip: 10.1.0.1           # LAN side (ens19, net1); must equal gateway
    wan_ip: 192.168.1.13   # WAN side (ens18, net0), on the upstream network
    settings:
      # All optional; these are the defaults.
      dns_servers: [1.1.1.1, 9.9.9.9]                         # upstream DNS
      blocked_networks: [192.168.0.0/16, 172.16.0.0/12, 10.0.0.0/8]
      # vpn: ...           # off when unset; see VPN below
```

The rest comes from the other hosts in the file: [DNS names](#dns-names) for every host and proxy route, and [port forwards](#port-forwards) from their `expose:` entries. Redeploy the router after adding, removing or changing hosts. `deploy-network.yaml` deploys it first, so it always picks up changes.

## Files

| File | Purpose |
|---|---|
| `files/configuration.nix` | NixOS configuration: LAN and DMZ interfaces, NAT, firewall, DHCP, DNS, VPN |
| `templates/router-vars.nix.j2` | Generates `router-vars.nix`, which passes the network file's values to `configuration.nix` |
| `templates/wg-client.conf.j2` | VPN client configuration files |
| `files/wg-keypair.py` | Makes WireGuard keys on your machine |
| `tasks/prepare.yml` | Creates the bridges if missing, makes the VPN's keys |
| `tasks/configure.yml` | Installs the configuration, switches, and checks LAN, DMZ, DNS, NAT, forwards and VPN |
| `tasks/verify.yml` | Tries each forward from your machine, writes VPN client files |
| `tasks/ports.yml` | Ports the [network check](../network_verify/README.md) expects it to listen on: 53 |

## How it works

Everything is in `configuration.nix`:

- **Interfaces:** `ens18` keeps the static home-LAN address from `network.nix`, like every other VM. `ens19` gets the LAN address, and `ens20` the [DMZ's](#dmz) when there is one.
- **NAT:** `networking.nat` masquerades LAN traffic leaving through `ens18` and turns on IPv4 forwarding. IPv6 isn't forwarded, so LAN clients have IPv4 only.
- **Forwarding firewall:** `networking.firewall.filterForward` drops forwarded traffic unless a rule accepts it. Rules, in order:
  1. Replies to connections the LAN started are accepted.
  2. LAN traffic to a blocked network is dropped.
  3. Other LAN traffic out through the WAN is accepted.

  The only traffic from the WAN side let into the LAN is the [port forwards](#port-forwards) from the hosts' `expose:` entries. Without any, home-LAN machines can't reach LAN VMs at all.

  A [DMZ](#dmz) adds its own rules around rule 2.
- **Firewall on the router itself:** from the LAN, only DHCP (UDP 67), DNS (53) and ping are allowed. SSH is only open on the WAN side.
- **DHCP and DNS:** dnsmasq listens only on `ens19` (and `ens20` with a DMZ, `wg0` with the VPN on). It hands out addresses with `10.1.0.1` as gateway and DNS server, answers for the [network's hosts](#dns-names), and forwards other DNS queries to `settings.dns_servers`.

The order matters for rule 2. The NixOS NAT module adds its own "accept LAN to WAN" rule, and the home LAN is also reached through the WAN. `configuration.nix` uses `lib.mkBefore` so the drop comes first.

LAN clients can still ping the router's WAN address, `192.168.1.13`, because ping is allowed on every interface. Nothing else on that address answers them.

## Deploying

```bash
source proxmox/.env
ansible-playbook playbooks/deploy-host.yaml -e network=lab -e host=router
```

Deploy the router before anything else on its network: every other VM there is reached over SSH through it. Besides the steps every host goes through, the deploy:

1. Creates the network's bridge (`vmbr1`) if it doesn't exist, with no physical port and no address on the Proxmox host, so the host isn't reachable from the isolated network. This needs `Sys.Modify` on the node. It stops if a bridge of that name exists with a port or address, or if other network changes are already staged on the node, because applying the bridge would apply them too. Apply or revert those in the Proxmox UI, or pass `-e isolated_bridge_apply_pending=true`.
2. Makes the [VPN's](#vpn) keys, if it is on.
3. Adds net1 on the bridge, and checks the card shows up as `ens19`. With a [DMZ](#dmz), it also creates the DMZ bridge and adds net2 on it as `ens20`.
4. Switches to the configuration. A live switch doesn't add the LAN address on its own, because NixOS only sets it when `ens19` appears, and `ens19` has been there since boot. The deploy starts that step (`network-addresses-ens19.service`) itself.
5. Checks the LAN address, IP forwarding, dnsmasq, every DNS name, the blocking rule, each port forward and the VPN, and that the router reaches the upstream DNS servers over TCP. It doesn't use ping, because the home network drops outbound ping.
6. Tries each TCP port forward from your machine, and writes the VPN's client files.

[proxmox/scripts/isolated-bridge.yaml](../../proxmox/scripts/isolated-bridge.yaml) creates a bridge on its own, if you want one before any router.

## Using the isolated network

Hosts in the network file get fixed addresses outside the DHCP range, with the router as gateway and DNS server. A VM you attach to `vmbr1` by hand gets an address by DHCP. Ansible reaches the network's VMs over SSH through the router; see [Moving a VM between networks](../../README.md#moving-a-vm-between-networks) for doing the same by hand.

To check isolation from a LAN VM:

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

## DNS names

The router's DNS server answers for every host in its network file, by name alone and under the network's domain, which defaults to `<network>.home.arpa` (`home.arpa` is reserved for home networks by [RFC 8375](https://www.rfc-editor.org/rfc/rfc8375)):

```bash
# from a VM on the isolated network
ping postgres
psql -h postgres.lab.home.arpa -U pgadmin -d postgres
```

Names in the domain are never sent to the upstream DNS servers, and DHCP clients get the domain as their search domain. Set `domain:` in the network's `network:` block to use another one. The deploy asks the router's DNS server for each name and stops if an answer is wrong. Adding or removing a host changes the records, so redeploy the router afterwards.

Home-LAN machines use the home router for DNS, so these names don't work from there.

## DMZ

A DMZ is a second bridge behind the router, for hosts reached from outside the network. It is set in the network's `dmz:` block, and hosts join it with `zone: dmz`. See [networks/README.md](../../networks/README.md#dmz) for the settings.

```
                                  ens19 10.1.0.1 ── vmbr1 ── LAN: gitea, postgres, ...
vmbr0 ── ens18 [router] ──┤
         192.168.1.13            ens20 10.1.1.1 ── vmbr2 ── DMZ: proxy, ...
```

The router treats the DMZ like the LAN (NAT to the internet, DNS, no SSH to the router, no private networks), except for the LAN:

1. **DMZ rules** are accepted first. Each lets one DMZ host reach one LAN host on one port. They come from the proxy's routes, when the proxy is in the DMZ, and from `reach:` entries.
2. LAN to DMZ is accepted.
3. LAN traffic to private networks is dropped (the existing rule).
4. DMZ traffic to private networks is dropped. That includes the LAN, and the VPN.
5. VPN clients may reach the LAN and the DMZ.

Rules 1 and 2 have to come before the drops, because the DMZ's subnet is a private network too.

DHCP is off in the DMZ unless `dmz.dhcp` is set, so a VM attached to the DMZ bridge by hand gets no address. DNS is answered on the DMZ address, which is the DMZ hosts' DNS server.

**Adding a DMZ to a running router:** add the `dmz:` block and redeploy the router. The deploy creates the bridge and adds net2 to the running VM. Proxmox hotplugs it when the VM's Hotplug options include Network, which they do by default. The deploy stops before switching if `ens20` hasn't appeared. Then reboot the router, or turn on network hotplug, and deploy again.

The deploy checks `ens20`'s address, that the DNS server answers there, and that each DMZ rule is in place. To see the rules and how much the DMZ drop has caught:

```bash
sudo nft list chain inet nixos-fw forward-allow | grep -i dmz
```

## VPN

A WireGuard VPN lets your own devices into the isolated network. Turn it on in the router's settings:

```yaml
    settings:
      vpn:
        cidr: 10.201.0.0/24      # the VPN's own subnet; the router is .1
        # port: 51820            # UDP, on the router's WAN address
        # endpoint: vpn.example.com   # what clients connect to; defaults to wan_ip
        peers:
          - name: laptop
            ip: 10.201.0.2
          - name: phone
            ip: 10.201.0.3
            # public_key: ...    # if the device made its own key
```

Then redeploy the router. The deploy:

1. Makes a key pair for the router, and for each peer without a `public_key`, in `secrets/<network>/vpn/` on your machine. Existing keys are kept, so a rebuilt router keeps working with existing clients.
2. Copies the router's private key to `/var/lib/wireguard/wg0.key` on the router, outside the Nix store.
3. Checks that `wg0` has the router's key, the port and exactly the listed peers.
4. Writes a client file for each peer, `secrets/<network>/vpn/<peer>.conf`. Import it into the WireGuard app, or run `wg-quick up ./laptop.conf`. A peer with its own `public_key` gets a file with a placeholder where its private key goes.

**What clients get:** an address in the VPN subnet, and a tunnel for only the network's subnet (and its DMZ's) and the VPN's. Other traffic, including to the internet, doesn't go through it. They use the router's DNS server, so names like `postgres.lab.home.arpa` and the [proxy's](../proxy/README.md) routes work. They can also SSH to the router at its VPN address. Lab hosts can't start connections to VPN clients, because the VPN subnet is inside the blocked private ranges.

**Postgres:** when `settings.allowed_networks` is unset, postgres on the network also allows password logins from the VPN subnet.

**From outside the home:** the default endpoint is the router's WAN address, which only works from the home LAN. To connect from the internet, forward the UDP port on your home router to the router's WAN address (pfSense: Firewall > NAT > Port Forward). Then set `endpoint` to your public address or a name for it, and redeploy the router to update the client files.

**Removing a peer:** delete it from `peers` and redeploy the router. Its files in `secrets/<network>/vpn/` are left in place; delete them yourself.

Validation stops before anything changes if:

- the VPN subnet overlaps any network or other VPN,
- a peer's address isn't in the subnet, is the router's (`.1`), or is another peer's,
- two peers share a name, or a peer has the router's name,
- a `public_key` isn't a WireGuard key,
- the port is already used by a UDP `expose:` entry.

## Port forwards

A port forward makes a service on a LAN VM, such as a website, reachable from the home network at the router's WAN address. List the ports under `expose:` on the host they go to, in the network file:

```yaml
  - name: postgres
    type: postgres
    ip: 10.1.0.12
    expose:
      - port: 5432          # the port on the host
        # wan_port: 15432   # the port on the router; defaults to port
        # proto: udp        # defaults to tcp
        # name: db          # needed when a host exposes more than one port
```

Then redeploy the router, which builds its forwards from every host's `expose:` entries:

```bash
source proxmox/.env
ansible-playbook playbooks/deploy-host.yaml -e network=lab -e host=router
```

The router is updated in place. Then each TCP forward is tried from your machine and the result is reported. A forward only answers once the service on the VM is running, so "not answering" usually means the VM or its service isn't up yet. UDP forwards can't be tested this way and are only listed.

An [external proxy route](../proxy/README.md#external-routes) on the network also forwards the router's TCP 443 and 80 to the proxy, without any `expose:` entry.

To remove a forward, delete the `expose:` entry and redeploy the router. `deploy-network.yaml` deploys the router first, so it always picks up changes.

Validation stops before anything changes if an entry:

- has a protocol other than `tcp` or `udp`, or a port outside 1–65535,
- uses the same protocol and router port as another entry on the network,
- uses TCP 22 on the router. That is the router's own SSH, and forwarding it would lock the playbook out. Forward another `wan_port` to the host's 22 instead.
- is on a home network, where hosts are reached directly, or on the router itself.

Hosts always have fixed addresses outside the DHCP range, so a forward can't end up pointing at nothing. After switching, the router also checks each forward's address is on its LAN.

**What a forward allows:** new connections to `192.168.1.13:<wan_port>` from the home network are passed to the VM, and the VM's replies go back. The VM still can't start connections to the home LAN; the private-network block applies to it like to any LAN VM.

**From LAN VMs:** other VMs on the isolated LAN reach the service at its LAN address (such as `postgres.lab.home.arpa`), not at `192.168.1.13`. Forwards only apply to traffic arriving on the WAN side.

**From the internet:** the router's WAN address is a private home-LAN address, so the internet can't reach it directly. Also forward the port on the home router (pfSense: Firewall > NAT > Port Forward) to `192.168.1.13` on the same port. This only works if your ISP gives your home router a public address. An address in `100.64.0.0/10` on its WAN interface means it's behind carrier-grade NAT and can't take incoming connections. Opening a service to the internet exposes it to everyone, so keep it patched.

To see the forwards that are in place, on the router:

```bash
sudo nft list chain ip nixos-nat pre
```

## Firewall commands

The firewall is nftables, generated from `files/configuration.nix`. Run these on the router (`ssh admin@192.168.1.13`).

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

Rules you change by hand with `nft` are lost at the next reload, and so are ports opened with `nixos-firewall-tool`. To keep a change, edit `files/configuration.nix` and redeploy the router. For example:

```nix
# Open a port on the router's WAN side only.
networking.firewall.interfaces.${wan}.allowedTCPPorts = [ 22 8080 ];
```

This opens a port on the router itself. To pass a port through to a LAN VM, use [port forwards](#port-forwards) instead.

Keep `22` in the WAN list. The playbook logs in over SSH on the WAN, and the `admin` user has no password, so there is no other way in.

## Making changes

Edit the router's entry or the files here and redeploy the router. An existing VM is updated in place.

- **LAN subnet, gateway or DHCP range:** change them in the network's `network:` block. Keep the DHCP range inside the subnet, keep hosts' addresses outside it, and don't overlap other networks. Validation checks all of this.
- **DNS servers or blocked networks:** change them under `settings:`.
- **Port forwards, DNS names:** change the other hosts' entries, then redeploy the router.
- **NixOS settings:** edit [files/configuration.nix](files/configuration.nix). Leave the values above out; they come from the network file.

## Removing the router

```bash
ansible-playbook playbooks/destroy-host.yaml -e network=lab -e host=router
```

This permanently deletes the VM. It refuses while other VMs of its network still exist, since they would lose their only way out. It asks you to type the host name.

The bridges stay. To remove the whole network, routers last, and its bridges (the DMZ's too):

```bash
ansible-playbook playbooks/destroy-network.yaml -e network=lab -e remove_bridge=true
```
