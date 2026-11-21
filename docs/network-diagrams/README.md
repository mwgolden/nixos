# Network diagrams

One file per network, written when the network is deployed or changed. Don't edit them: redeploy, or run `playbooks/diagram-network.yaml`, to update them.

| Network | Type | Subnet | Bridge | Router WAN | Hosts deployed |
|---|---|---|---|---|---|
| [agent-developer](agent-developer.md) | isolated | 10.3.1.0/24 | vmbr10 | 192.168.1.31 | 7 of 7 |
| [home](home.md) | home | 192.168.1.0/24 | vmbr0 | — | 2 of 2 |

```mermaid
flowchart TB
    n_agent_developer["agent-developer<br/>10.3.1.0/24 on vmbr10<br/>DMZ 10.3.2.0/24 on vmbr11<br/>7 hosts"]
    n_home["home<br/>192.168.1.0/24 on vmbr0<br/>2 hosts"]
    n_home <-->|"router WAN 192.168.1.31"| n_agent_developer
```
