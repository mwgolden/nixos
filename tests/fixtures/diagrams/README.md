# Network diagrams

One file per network, written when the network is deployed or changed. Don't edit them: redeploy, or run `playbooks/diagram-network.yaml`, to update them.

| Network | Type | Subnet | Bridge | Router WAN | Hosts deployed |
|---|---|---|---|---|---|
| [home](home.md) | home | 192.168.1.0/24 | vmbr0 | — | 3 of 3 |
| [lab](lab.md) | isolated | 10.1.0.0/24 | vmbr1 | 192.168.1.13 | 4 of 4 |

```mermaid
flowchart TB
    n_home["home<br/>192.168.1.0/24 on vmbr0<br/>3 hosts"]
    n_lab["lab<br/>10.1.0.0/24 on vmbr1<br/>DMZ 10.1.1.0/24 on vmbr7<br/>4 hosts"]
    n_home <-->|"router WAN 192.168.1.13"| n_lab
```
