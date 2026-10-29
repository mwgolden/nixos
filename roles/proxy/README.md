# Reverse proxy

A NixOS VM running [Caddy](https://caddyserver.com/) that serves web services on its network under HTTPS names, such as `https://git.lab.home.arpa/`. Each route is a `proxy:` entry on the host it goes to, so the proxy itself has no settings.

```yaml
hosts:
  - name: gitea
    type: gitea
    ip: 10.1.0.14
    proxy:
      - name: git      # served as git.<domain>, here git.lab.home.arpa
        port: 3000     # the port on gitea

  - name: proxy
    type: proxy
    vm_id: 116
    ip: 10.1.0.10
```

Deploy it like any other host, then redeploy the router so its DNS server knows the new names:

```bash
source proxmox/.env
ansible-playbook playbooks/deploy-host.yaml -e network=lab -e host=proxy
ansible-playbook playbooks/deploy-host.yaml -e network=lab -e host=router
```

`deploy-network.yaml` does both, since it deploys the router first.

## Rules

Validation stops before anything changes if:

- a network has routes but no `proxy` host, or more than one `proxy` host,
- two routes on a network have the same name, or a route has the same name as a host (both would be the same DNS name),
- a route's name isn't a single DNS label, or its port isn't 1–65535,
- the proxy or a router has `proxy:` entries,
- a route is `external` on a home network, or the router's TCP 443 or 80 is already forwarded elsewhere.

Routes only go to hosts on the proxy's own network. Isolated networks can't reach each other, so a proxy couldn't reach a host on another network anyway.

## HTTPS

Each route gets a certificate from Caddy's own certificate authority (`tls internal`), and plain HTTP is redirected to HTTPS. The authority lives on the proxy VM. After each deploy its root certificate is copied to `secrets/<network>/<proxy>-ca.crt` on your machine. Trust that file once, and browsers stop warning:

| System | How |
|---|---|
| Linux (Debian, Ubuntu) | `sudo cp secrets/lab/proxy-ca.crt /usr/local/share/ca-certificates/nixlab-lab.crt && sudo update-ca-certificates` |
| NixOS | Add the file to `security.pki.certificateFiles` |
| macOS | Open it in Keychain Access, then set it to "Always Trust" |
| Firefox | Settings > Privacy & Security > Certificates > View Certificates > Authorities > Import |

The certificate is named `nixlab <network> <proxy>`. If the proxy VM is destroyed and created again, it makes a new authority, which has to be trusted again.

## Who can reach it

Routes are internal by default. On an isolated network, the router's DNS server points each route's name at the proxy, so VMs on that network and VPN clients can use them. Caddy turns away connections to an internal route from anywhere else.

### External routes

To publish a route outside its isolated network, mark it external:

```yaml
    proxy:
      - name: git
        port: 3000
        external: true
```

Then redeploy the router and the proxy (`deploy-network` does both). As soon as one route on the network is external:

- The router forwards its TCP 443 and 80 to the proxy. Nothing else needs `expose:`.
- External routes answer anyone who reaches the router's address, `192.168.1.13`.
- Internal routes still refuse connections from outside the network and its VPN, even through that forward. Forwarded connections keep their home address, so Caddy can tell.

Caddy picks the route by name, so the address alone (`https://192.168.1.13/`) matches nothing. Home machines ask the home router for names, so point each external name at the router's WAN address, `192.168.1.13`, in one of two places. The deploy lists the names to add.

- On the home router, for every machine at home (pfSense: Services > DNS Resolver > Host Overrides), such as `git.lab.home.arpa` → `192.168.1.13`.
- In `/etc/hosts` on one machine. One line can hold several names:

  ```text
  192.168.1.13  git.lab.home.arpa  other.lab.home.arpa
  ```

This only works for external routes. Pointing an internal route's name at `192.168.1.13` reaches the proxy, but it refuses the connection because it comes from a home address. Use the VPN for internal routes. VPN clients use the lab router's DNS, so they need neither of these.

From the internet, you'd also forward 443 on the home router to the router's WAN address. Then the route is open to everyone, so keep the service patched and its logins strong.

Validation refuses `external` on a home network, where the whole LAN already reaches the proxy. It also refuses it when the router's TCP 443 or 80 is already used by an `expose:` entry.

### Home networks

A home network has no DNS server from this project. To use a home proxy's names, point each at the proxy's address on the home router (pfSense: Services > DNS Resolver > Host Overrides).

Only HTTP services can be proxied. Databases and SSH are reached directly.

## Checks

After switching, the deploy asks Caddy for each route on the proxy itself:

- No HTTPS answer stops the deploy. See `journalctl -u caddy` on the proxy.
- 502 is reported but not fatal. It means the backend isn't answering, usually because it isn't deployed yet.
