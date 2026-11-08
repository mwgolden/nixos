# Network home

Generated from [networks/home.yaml](../../networks/home.yaml) when the network is deployed or changed. Don't edit it: redeploy, or run `playbooks/diagram-network.yaml`, to update it.

Home network 192.168.1.0/24 on vmbr0. 1 of 1 host deployed.

```mermaid
flowchart TB
    subgraph net["home 192.168.1.0/24 on vmbr0<br/>gateway 192.168.1.1, DHCP by the home router"]
        gw["home gateway and DNS<br/>192.168.1.1"]
        h_nats["nats, VM 118<br/>nats, 192.168.1.18"]
        r_lab["router of lab, VM 113<br/>WAN 192.168.1.13"]
        r_workstation_lab["router of workstation-lab, VM 223<br/>WAN 192.168.1.3<br/>not deployed"]
    end
    gw <--> h_nats
    gw <--> r_lab
    gw <--> r_workstation_lab
    classDef pending stroke-dasharray: 5 5
    class r_workstation_lab pending
```

## Hosts

| Host | Type | VM ID | Zone | Address | Ports | Data disk | Deployed |
|---|---|---|---|---|---|---|---|
| nats | nats | 118 | lan | 192.168.1.18 | — | 20 GB on local-lvm | yes |
