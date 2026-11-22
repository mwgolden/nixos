# Network agent-developer

Generated from [networks/agent-developer.yaml](../../networks/agent-developer.yaml) when the network is deployed or changed. Don't edit it: redeploy, or run `playbooks/diagram-network.yaml`, to update it.

Isolated network 10.3.1.0/24 on vmbr10, behind router on home at 192.168.1.31. DNS domain agent-developer.home.arpa. 8 of 8 hosts deployed. TLS certificates from the home.openbao root.

```mermaid
flowchart TB
    up["home 192.168.1.0/24 on vmbr0<br/>gateway 192.168.1.1"]
    h_router["router, VM 301<br/>WAN 192.168.1.31<br/>LAN 10.3.1.1<br/>DMZ 10.3.2.1<br/>NAT, firewall, DHCP, DNS"]
    subgraph lan["LAN 10.3.1.0/24 on vmbr10<br/>DHCP .100 to .199"]
        h_gitea["gitea, VM 303<br/>gitea, 10.3.1.2<br/>tcp 3000"]
        h_dev_workstation["dev-workstation, VM 304<br/>workstation, 10.3.1.3<br/>tcp 22"]
        h_garage["garage, VM 305<br/>garage, 10.3.1.4"]
        h_openbao["openbao, VM 306<br/>openbao, 10.3.1.5"]
        h_postgres["postgres, VM 307<br/>postgres, 10.3.1.6<br/>tcp 5432"]
        h_monitoring["monitoring, VM 308<br/>monitoring, 10.3.1.7<br/>tcp 3000"]
    end
    subgraph dmz["DMZ 10.3.2.0/24 on vmbr11<br/>no DHCP"]
        h_web_proxy["web-proxy, VM 302<br/>proxy, 10.3.2.3<br/>tcp 443, tcp 80"]
    end
    ca(["TLS root home.openbao<br/>intermediate pki-agent-developer, agent-developer.home.arpa"])
    up <-->|"ens18 WAN 192.168.1.31"| h_router
    h_router <-->|"ens19 LAN 10.3.1.1"| lan
    h_router <-->|"ens20 DMZ 10.3.2.1"| dmz
    up -.->|"external routes 192.168.1.31:443<br/>git.agent-developer.home.arpa, grafana.agent-developer.home.arpa"| h_web_proxy
    up -.->|"port forward tcp 192.168.1.31:2222"| h_dev_workstation
    up -.->|"port forward tcp 192.168.1.31:5432"| h_postgres
    h_web_proxy -.->|"route git (external), tcp 3000"| h_gitea
    h_web_proxy -.->|"route grafana (external), tcp 3000"| h_monitoring
    ca -.->|"certificates, issued at deploy"| lan
    ca -.->|"certificates, issued at deploy"| dmz
    lan -.->|"outbound, NAT through 192.168.1.31"| up
    lan -.-x|"blocked: 192.168.0.0/15, 172.16.0.0/12, 10.0.0.0/8"| up
```

## Hosts

| Host | Type | VM ID | Zone | Address | Ports | Data disk | Deployed |
|---|---|---|---|---|---|---|---|
| router | router | 301 | router | 192.168.1.31 (LAN 10.3.1.1) | — | — | yes |
| web-proxy | proxy | 302 | dmz | 10.3.2.3 | tcp 443, tcp 80 | — | yes |
| gitea | gitea | 303 | lan | 10.3.1.2 | tcp 3000 | 40 GB on local-lvm | yes |
| dev-workstation | workstation | 304 | lan | 10.3.1.3 | tcp 22 | — | yes |
| garage | garage | 305 | lan | 10.3.1.4 | — | 20 GB on local-lvm | yes |
| openbao | openbao | 306 | lan | 10.3.1.5 | — | 10 GB on local-lvm | yes |
| postgres | postgres | 307 | lan | 10.3.1.6 | tcp 5432 | 20 GB on local-lvm | yes |
| monitoring | monitoring | 308 | lan | 10.3.1.7 | tcp 3000 | 20 GB on local-lvm | yes |

## Software

Packages and tools declared in the network file. Each role's README lists what the role installs itself.

| Host | Packages | Tools |
|---|---|---|
| dev-workstation | uv, nodejs_22, openbao | @anthropic-ai/claude-code (npm), ruff (uv) |

## TLS certificates

Every host here gets a certificate from home.openbao (on network home) when it is deployed. Machines that trust secrets/home/openbao-pki-root.crt trust them all.

| Issued by | Intermediate | Names | Root to trust |
|---|---|---|---|
| home.openbao | pki-agent-developer | *.agent-developer.home.arpa | secrets/home/openbao-pki-root.crt |

## Port forwards

From the router's WAN address, 192.168.1.31.

| Name | Protocol | WAN port | To |
|---|---|---|---|
| dev-workstation | tcp | 2222 | dev-workstation 10.3.1.3:22 |
| postgres | tcp | 5432 | postgres 10.3.1.6:5432 |
| web-proxy-https | tcp | 443 | web-proxy 10.3.2.3:443 |
| web-proxy-http | tcp | 80 | web-proxy 10.3.2.3:80 |

## Proxy routes

Served by web-proxy.

| Route | Name | Backend | External |
|---|---|---|---|
| git | git.agent-developer.home.arpa | gitea 10.3.1.2:3000 | yes |
| grafana | grafana.agent-developer.home.arpa | monitoring 10.3.1.7:3000 | yes |

## DMZ to LAN rules

| From | To | Port |
|---|---|---|
| web-proxy 10.3.2.3 | gitea 10.3.1.2 | tcp 3000 |
| web-proxy 10.3.2.3 | monitoring 10.3.1.7 | tcp 3000 |
