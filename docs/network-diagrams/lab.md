# Network lab

Generated from [networks/lab.yaml](../../networks/lab.yaml) when the network is deployed or changed. Don't edit it: redeploy, or run `playbooks/diagram-network.yaml`, to update it.

Isolated network 10.1.0.0/24 on vmbr1, behind router on home at 192.168.1.13. DNS domain lab.home.arpa. 5 of 5 hosts deployed.

```mermaid
flowchart TB
    up["home 192.168.1.0/24 on vmbr0<br/>gateway 192.168.1.1"]
    h_router["router, VM 113<br/>WAN 192.168.1.13<br/>LAN 10.1.0.1<br/>DMZ 10.1.1.1<br/>NAT, firewall, DHCP, DNS"]
    subgraph lan["LAN 10.1.0.0/24 on vmbr1<br/>DHCP .100 to .199"]
        h_postgres["postgres, VM 112<br/>postgres, 10.1.0.12<br/>tcp 5432"]
        h_gitea["gitea, VM 114<br/>gitea, 10.1.0.14<br/>tcp 3000"]
        h_webserver_lab["webserver-lab, VM 111<br/>webserver, 10.1.0.11<br/>tcp 80"]
    end
    subgraph dmz["DMZ 10.1.1.0/24 on vmbr4<br/>no DHCP"]
        h_proxy["proxy, VM 116<br/>proxy, 10.1.1.10<br/>tcp 443, tcp 80"]
    end
    up <-->|"ens18 WAN 192.168.1.13"| h_router
    h_router <-->|"ens19 LAN 10.1.0.1"| lan
    h_router <-->|"ens20 DMZ 10.1.1.1"| dmz
    up -.->|"external routes 192.168.1.13:443<br/>git.lab.home.arpa, www.lab.home.arpa"| h_proxy
    up -.->|"port forward tcp 192.168.1.13:5432"| h_postgres
    h_proxy -.->|"route git (external), tcp 3000"| h_gitea
    h_proxy -.->|"route www (external), tcp 80"| h_webserver_lab
    lan -.->|"outbound, NAT through 192.168.1.13"| up
    lan -.-x|"blocked: 192.168.0.0/16, 172.16.0.0/12, 10.0.0.0/8"| up
```

## Hosts

| Host | Type | VM ID | Zone | Address | Ports | Data disk | Deployed |
|---|---|---|---|---|---|---|---|
| router | router | 113 | router | 192.168.1.13 (LAN 10.1.0.1) | — | — | yes |
| postgres | postgres | 112 | lan | 10.1.0.12 | tcp 5432 | 20 GB on local-lvm | yes |
| proxy | proxy | 116 | dmz | 10.1.1.10 | tcp 443, tcp 80 | — | yes |
| gitea | gitea | 114 | lan | 10.1.0.14 | tcp 3000 | 40 GB on local-lvm | yes |
| webserver-lab | webserver | 111 | lan | 10.1.0.11 | tcp 80 | — | yes |

## Port forwards

From the router's WAN address, 192.168.1.13.

| Name | Protocol | WAN port | To |
|---|---|---|---|
| postgres | tcp | 5432 | postgres 10.1.0.12:5432 |
| proxy-https | tcp | 443 | proxy 10.1.1.10:443 |
| proxy-http | tcp | 80 | proxy 10.1.1.10:80 |

## Proxy routes

Served by proxy.

| Route | Name | Backend | External |
|---|---|---|---|
| git | git.lab.home.arpa | gitea 10.1.0.14:3000 | yes |
| www | www.lab.home.arpa | webserver-lab 10.1.0.11:80 | yes |

## DMZ to LAN rules

| From | To | Port |
|---|---|---|
| proxy 10.1.1.10 | gitea 10.1.0.14 | tcp 3000 |
| proxy 10.1.1.10 | webserver-lab 10.1.0.11 | tcp 80 |
