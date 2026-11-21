# Network home

Generated from [networks/home.yaml](../../networks/home.yaml) when the network is deployed or changed. Don't edit it: redeploy, or run `playbooks/diagram-network.yaml`, to update it.

Home network 192.168.1.0/24 on vmbr0. 3 of 3 hosts deployed.

```mermaid
flowchart TB
    subgraph net["home 192.168.1.0/24 on vmbr0<br/>gateway 192.168.1.1, DHCP by the home router"]
        gw["home gateway and DNS<br/>192.168.1.1"]
        h_nats["nats, VM 118<br/>nats, 192.168.1.18"]
        h_ws["ws, VM 109<br/>workstation, 192.168.1.19"]
        h_openbao["openbao, VM 120<br/>openbao, 192.168.1.20"]
        r_agent_developer["router of agent-developer, VM 301<br/>WAN 192.168.1.31"]
        r_lab["router of lab, VM 113<br/>WAN 192.168.1.13"]
        r_workstation_lab["router of workstation-lab, VM 223<br/>WAN 192.168.1.3<br/>not deployed"]
    end
    gw <--> h_nats
    gw <--> h_ws
    gw <--> h_openbao
    gw <--> r_agent_developer
    gw <--> r_lab
    gw <--> r_workstation_lab
    classDef pending stroke-dasharray: 5 5
    class r_workstation_lab pending
```

## Hosts

| Host | Type | VM ID | Zone | Address | Ports | Data disk | Deployed |
|---|---|---|---|---|---|---|---|
| nats | nats | 118 | lan | 192.168.1.18 | — | 20 GB on local-lvm | yes |
| ws | workstation | 109 | lan | 192.168.1.19 | — | — | yes |
| openbao | openbao | 120 | lan | 192.168.1.20 | — | 10 GB on local-lvm | yes |

## Software

Packages and tools declared in the network file. Each role's README lists what the role installs itself.

| Host | Packages | Tools |
|---|---|---|
| ws | python3Packages.ipython, uv, nodejs_22 | @anthropic-ai/claude-code (npm), ruff@0.8.4 (uv) |
