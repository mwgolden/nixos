# Network home

Generated from [networks/home.yaml](../../networks/home.yaml) when the network is deployed or changed. Don't edit it: redeploy, or run `playbooks/diagram-network.yaml`, to update it.

Home network 192.168.1.0/24 on vmbr0. 4 of 4 hosts deployed. TLS certificates from the home.openbao root.

```mermaid
flowchart TB
    subgraph net["home 192.168.1.0/24 on vmbr0<br/>gateway 192.168.1.1, DHCP by the home router"]
        gw["home gateway and DNS<br/>192.168.1.1"]
        h_webserver["webserver, VM 111<br/>webserver, 192.168.1.11"]
        h_gitea["gitea, VM 114<br/>gitea, 192.168.1.14"]
        h_garage["garage, VM 115<br/>garage, 192.168.1.15"]
        h_openbao["openbao, VM 121<br/>openbao, 192.168.1.20<br/>TLS root, signs this network's certificates"]
        r_lab["router of lab, VM 113<br/>WAN 192.168.1.13"]
    end
    gw <--> h_webserver
    gw <--> h_gitea
    gw <--> h_garage
    gw <--> h_openbao
    gw <--> r_lab
```

## Hosts

| Host | Type | VM ID | Zone | Address | Ports | Data disk | Deployed |
|---|---|---|---|---|---|---|---|
| webserver | webserver | 111 | lan | 192.168.1.11 | — | — | yes |
| gitea | gitea | 114 | lan | 192.168.1.14 | — | 40 GB on local-lvm | yes |
| garage | garage | 115 | lan | 192.168.1.15 | — | 128 GB on local-lvm | yes |
| openbao | openbao | 121 | lan | 192.168.1.20 | — | 10 GB on local-lvm | yes |

## TLS certificates

Every host here gets a certificate from home.openbao (on this network) when it is deployed. Machines that trust secrets/home/openbao-pki-root.crt trust them all.

| Issued by | Intermediate | Names | Root to trust |
|---|---|---|---|
| home.openbao | pki-home | *.home.home.arpa | secrets/home/openbao-pki-root.crt |

openbao is a TLS root. It signs certificates for home, lab.
