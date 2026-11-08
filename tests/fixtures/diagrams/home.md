# Network home

Generated from [networks/home.yaml](../../networks/home.yaml) when the network is deployed or changed. Don't edit it: redeploy, or run `playbooks/diagram-network.yaml`, to update it.

Home network 192.168.1.0/24 on vmbr0. 3 of 3 hosts deployed.

```mermaid
flowchart TB
    subgraph net["home 192.168.1.0/24 on vmbr0<br/>gateway 192.168.1.1, DHCP by the home router"]
        gw["home gateway and DNS<br/>192.168.1.1"]
        h_webserver["webserver, VM 111<br/>webserver, 192.168.1.11"]
        h_gitea["gitea, VM 114<br/>gitea, 192.168.1.14"]
        h_garage["garage, VM 115<br/>garage, 192.168.1.15"]
        r_lab["router of lab, VM 113<br/>WAN 192.168.1.13"]
    end
    gw <--> h_webserver
    gw <--> h_gitea
    gw <--> h_garage
    gw <--> r_lab
```

## Hosts

| Host | Type | VM ID | Zone | Address | Ports | Data disk | Deployed |
|---|---|---|---|---|---|---|---|
| webserver | webserver | 111 | lan | 192.168.1.11 | — | — | yes |
| gitea | gitea | 114 | lan | 192.168.1.14 | — | 40 GB on local-lvm | yes |
| garage | garage | 115 | lan | 192.168.1.15 | — | 128 GB on local-lvm | yes |
