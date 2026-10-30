# Architecture: Proxmox Lab Infrastructure

## 1. Purpose

This project provides a declarative, Ansible-driven system for creating and managing virtual machines and logical networks on Proxmox.

All virtual machines are NixOS machines cloned from a Proxmox VM template. Ansible manages VM provisioning, guest configuration, service installation, and removal.

The system supports multiple network configurations with different networking and security requirements. Examples include:

- **Isolated networks:** Hosts connect to a dedicated Proxmox bridge and use a firewall VM as their gateway for routing and internet access.
- **Home-network deployments:** Hosts connect to the home network without being placed behind an isolated-network firewall.
- **Optional services:** Networks can select services such as a reverse proxy, VPN server, DNS server, Gitea, Garage (S3-compatible object storage), PostgreSQL, and LDAP.

The system should make it possible to create a network by defining its desired hosts and services in configuration rather than manually provisioning each VM and configuring its dependencies.

## 2. Architectural principles

1. **Declarative configuration:** Configuration describes the desired state of a network and its hosts.
2. **Separation of responsibilities:** Host lifecycle management, network orchestration, and network infrastructure have distinct responsibilities.
3. **Reusable NixOs configurations:** Each host type has its own nix configurations for configuring the VM.
4. **Reusable host playbooks:** Each host type has its own playbooks for creating and removing the VM and configuring its software.
5. **Network-level orchestration:** A network playbook coordinates host lifecycle playbooks and manages network-specific resources.
6. **Consistent VM provisioning:** All VMs are cloned from the designated Proxmox NixOS template.
7. **Explicit networking:** Network membership, IP addresses, bridges, gateways, and access policies are defined rather than inferred from manual configuration.
8. **Optional services:** Services are deployed only when selected by the relevant configuration.
9. **Idempotency:** Repeated deployment should converge on the declared state without unnecessarily recreating existing resources.
10. **Controlled destruction:** Removing a host from configuration can result in resource deletion. Destructive actions must be explicit, documented, and appropriately guarded.
11. **Security by default:** Services and network access are restricted to their intended scope. Enabling a service must not implicitly expose it to the internet.

## 3. Conceptual model

The project has four primary concepts.

### 3.1 Network

A network is a logical deployment unit defined by a configuration file.

It specifies:

- Network identity and addressing.
- Proxmox networking resources.
- Network topology and isolation requirements.
- The hosts that belong to the network.
- Optional network-level services.
- Network-specific access and exposure policies.

A network configuration may represent an isolated network or a home-network deployment.

### 3.2 Host

A host represents a NixOS VM managed by the project.

A host definition specifies its identity, VM resources, network attachment, IP configuration, and desired software.

Host lifecycle playbooks are responsible for creating and removing individual hosts. They must be usable independently of the network orchestration playbook.

### 3.3 Service

A service represents software installed on a host or a network-level capability.

Examples include:

- Firewall and NAT.
- Internal DNS.
- Reverse proxy.
- VPN.
- Gitea.
- Garage (S3-compatible object storage).
- PostgreSQL.
- Static web server.
- LDAP.
- Other application and database services.

Services should be implemented through reusable Ansible roles or equivalent components. A service may require a dedicated VM, or it may be installed on an existing host when appropriate.

The architecture should distinguish between a service's installation and its network exposure. Installing a web application does not automatically make it publicly accessible.

### 3.4 Network orchestration

The network playbook reads a network configuration and reconciles the declared resources with the desired state.

It determines which hosts need to be created, which existing hosts need updating, and which previously managed hosts have been removed from the configuration.

It delegates individual host creation and removal to their respective lifecycle playbooks rather than duplicating host provisioning logic.

## 4. Network types and topology

### 4.1 Isolated network

An isolated network uses a dedicated Proxmox bridge that is not directly connected to the physical home LAN.

The network contains a firewall VM that provides the gateway for the network. The firewall is responsible for routing, NAT, and traffic filtering according to the network's policy.

Conceptually:

```text
Home LAN / Internet
        |
   Home router
        |
   Proxmox host
        |
   Isolated Proxmox bridge
        |
   +----+-------------------+
   |                        |
Firewall VM             Lab VMs
   |                    - Gitea
   |                    - Garage
   |                    - LDAP
   |                    - Other services
   |
Routing, NAT,
and firewall rules
```

The firewall VM must be attached to the isolated bridge and to the appropriate upstream network. Its upstream connectivity must be configured without unintentionally bridging the isolated network to the home LAN.

Hosts on the isolated network receive addresses from its configured subnet and use the firewall VM as their default gateway.

Outbound internet access and inbound access are separate policy decisions. Internet access from lab hosts must not imply that unsolicited internet traffic can reach them.

Access to the network for administration may be provided through a VPN or another explicitly configured administrative path.

### 4.2 Home-network deployment

A home-network deployment places VMs directly on the home network using an appropriate Proxmox bridge.

These hosts do not require the project's isolated-network firewall VM.

Conceptually:

```text
Home router
     |
Proxmox host
     |
Home-network Proxmox bridge
     |
+----+--------------------+
|                         |
NixOS VM              NixOS VM
Service A              Service B
```

The network configuration must identify this topology explicitly. The network orchestrator must not create an isolated firewall or dedicated isolated bridge for this network type unless separately requested.

Existing home-network routing, DHCP, DNS, and access policies remain external dependencies unless the configuration explicitly assigns those responsibilities to this project.

### 4.3 Network-type abstraction

Network-specific infrastructure should be implemented through reusable roles or components selected by the network configuration.

The orchestration layer should not contain duplicated host-provisioning logic for each network type.

A new network type should be possible without redesigning the lifecycle of every host.

## 5. Configuration model

Each network is defined by a separate configuration file.

A configuration describes the desired network and its member hosts. The exact schema should be finalized after inspecting the existing repository and its current provisioning implementation.

An illustrative configuration follows:

```yaml
network:
  name: dev-lab
  type: isolated

  addressing:
    cidr: 10.20.0.0/24
    gateway: 10.20.0.1

  proxmox:
    bridge: vmbr-lab

  firewall:
    enabled: true
    internet_access: true

  services:
    reverse_proxy:
      enabled: true

    dns:
      enabled: true

  hosts:
    - name: caddy
      type: reverse-proxy
      ip_address: 10.20.0.10
      template: nixos-server
      cpu: 2
      memory_mb: 2048
      disk_gb: 20

    - name: gitea
      type: gitea
      ip_address: 10.20.0.20
      template: nixos-server
      cpu: 2
      memory_mb: 4096
      disk_gb: 40
      proxy:
        - hostname: git.lab.example.com
          backend_port: 3000
```

This example is illustrative, not a finalized schema. The existing repository and implementation constraints should inform the final field names and structure.

### 5.1 Host identity and addressing

Each managed host must have a stable identity within the project.

The configuration must define or reference:

- Host name and unique identity.
- Proxmox VM identifier or an allocation strategy.
- VM template.
- CPU, memory, and storage requirements.
- Network attachment.
- IP address or an explicitly selected address-allocation mechanism.
- Desired host type and services.

Hosts requiring predictable SSH, DNS, or reverse-proxy access must receive predictable IP addresses.

Static guest configuration and DHCP reservations are both possible implementation strategies. The selected strategy must be compatible with the NixOS template and must be applied consistently during provisioning.

The system must detect conflicting VM identifiers, IP addresses, and host identities before creating resources.

### 5.2 Network membership

The host list in a network configuration defines the desired membership of that network.

- Adding a host declares that it should be provisioned and attached to the network.
- Removing a host declares that it should no longer belong to the desired network state.
- Updating a host definition declares the desired configuration change for that host.

The implementation must distinguish between removing a host from a network and deleting the underlying VM. For the initial implementation, configuration-driven deletion may be supported, but destructive behavior must be documented and guarded.

The system must not delete unrelated Proxmox VMs or resources that it does not own.

### 5.3 Service selection

Service selection determines which capabilities are deployed and configured.

A selected service may cause the orchestrator to create a dedicated host, configure an existing host, or enable a network-level resource.

Dependencies must be explicit. For example, a reverse-proxy route requires a valid backend host, a reachable backend address, and a configured backend port.

Enabling a service must not implicitly enable unrelated services or broaden network access.

## 6. Ansible responsibilities

### 6.1 Host lifecycle playbooks

Each host type is an Ansible role that holds its NixOS configuration and its service setup. Generic create and remove playbooks run the shared VM roles and then the host's type role, so each host type can still be created and removed on its own. (Ansible can't import a playbook by a variable name, so a network playbook can't loop over one playbook per host type. Roles can be included by name, which is what makes network orchestration possible.)

The host creation workflow is responsible for:

1. Validating host-specific configuration.
2. Cloning the VM from the Proxmox NixOS template when necessary.
3. Configuring VM resources and network interfaces.
4. Applying the host's network and IP configuration.
5. Establishing administrative access, including SSH.
6. Configuring the requested software and service roles.
7. Verifying that the host is operational.

The host removal workflow is responsible for removing the VM and associated resources owned by that host, subject to the project's deletion safeguards.

Host lifecycle playbooks must remain independently usable. The network orchestrator invokes them instead of reimplementing their functionality.

### 6.2 Network infrastructure roles

Network infrastructure roles manage resources shared by the network rather than by individual application hosts.

Examples include:

- Proxmox bridge configuration, where this project is responsible for managing it.
- Firewall VM lifecycle and configuration.
- Routing, NAT, and firewall rules.
- Network-level DNS.
- Network-level VPN configuration.

These roles must clearly identify which resources they own and how they interact with resources managed outside the project.

### 6.3 Network orchestration playbook

A network-level playbook is responsible for the lifecycle of an entire network.

Its responsibilities include:

1. Loading and validating the selected network configuration.
2. Determining the network type and required infrastructure.
3. Creating or configuring network resources.
4. Invoking host creation or update playbooks for declared hosts.
5. Configuring network-level services and host dependencies.
6. Configuring DNS records and reverse-proxy routes where requested.
7. Removing resources that are no longer part of the desired configuration, according to the configured lifecycle policy.
8. Validating the resulting deployment.

The network playbook coordinates these operations. It should not duplicate the implementation details of individual host or service roles.

### 6.4 Repository organization

The target layout, reached in stages (see [PLAN.md](PLAN.md)):

```text
.
├── ansible.cfg
├── bootstrap.sh                 # builds the NixOS template
├── networks/
│   ├── home.yaml                # VMs directly on the home LAN
│   └── lab.yaml                 # an isolated network behind a router VM
├── secrets/<network>/<host>.env # gitignored credentials
├── playbooks/
│   ├── validate-network.yaml
│   ├── deploy-network.yaml
│   ├── destroy-network.yaml
│   ├── deploy-host.yaml
│   └── destroy-host.yaml
├── roles/
│   ├── proxmox_vm/              # clone, data disk, NICs, start
│   ├── proxmox_vm_remove/       # guarded VM deletion
│   ├── nixos_base/              # common.nix, network.nix, placement, switch
│   ├── dotenv/                  # reads secrets files
│   ├── isolated_bridge/
│   ├── network_verify/          # checks at the end of deploy-network
│   ├── router/                  # firewall, NAT, DNS, WireGuard VPN
│   ├── webserver/
│   ├── postgres/
│   ├── gitea/
│   ├── garage/
│   ├── proxy/                   # Caddy reverse proxy (type: proxy)
│   └── ldap/                    # lldap (type: ldap)
├── modules/                     # NixOS modules shared by every VM
└── proxmox/                     # template bootstrap
```

Each type role keeps its NixOS files in `files/` and `templates/`.

## 7. Reverse proxy and service access

The reverse proxy is an optional service that routes HTTP/HTTPS requests to configured backend hosts.

Its configuration should be derived from the desired service definitions rather than maintained independently in several places.

For each route, the configuration identifies:

- Hostname.
- Backend host or address.
- Backend port.
- Relevant TLS configuration.
- Whether the route is internal-only or intended for external publication.

The reverse proxy may run on a dedicated NixOS VM or another explicitly selected host.

For an internal-only network, internal DNS can resolve service hostnames to the proxy's address. Access to the proxy and its backends is governed by network policy.

External publication requires explicit router port forwarding, firewall permissions, DNS, and appropriate TLS configuration. It must not be enabled by default.

Non-HTTP protocols, including direct database connections and SSH, are not automatically routed through an HTTP reverse proxy.

## 8. Security requirements

The following requirements apply regardless of network type:

- Administrative access must be restricted to intended sources.
- SSH must not be exposed to the public internet by default.
- Proxmox management access must remain restricted.
- Database services must not be publicly exposed by default.
- Isolated networks must not be bridged directly to the home LAN.
- Firewall rules must be derived from explicit requirements rather than broad implicit permissions.
- Public-facing services must not receive unrestricted access to other lab hosts.
- Credentials and private keys must not be embedded in network configuration files.
- Destructive operations must be identifiable and guarded.
- The system must distinguish resources managed by this project from pre-existing resources.

## 9. Lifecycle and reconciliation

The system should support both initial deployment and subsequent changes.

A deployment operation reconciles the environment with the selected network configuration.

Expected behavior includes:

- Creating missing resources.
- Updating managed resources when configuration changes.
- Leaving unchanged resources intact.
- Adding newly declared hosts.
- Applying host configuration changes through the appropriate host playbooks.
- Identifying hosts removed from the desired configuration.
- Removing obsolete resources only according to an explicit deletion policy.

The system must account for dependencies during both creation and deletion. For example, network infrastructure must not be removed while managed hosts still depend on it.

A failed deployment must not silently leave the network in an unsafe state. Where full rollback is impractical, failures should be reported clearly and subsequent runs should be able to reconcile the partially deployed environment.

## 10. Validation and testing

Before making changes, the system should validate configuration syntax, required values, uniqueness constraints, address ranges, and declared service dependencies.

Deployment validation should verify, where applicable:

- Expected VMs exist in Proxmox.
- VM network interfaces are attached to the intended bridge.
- Guest IP addresses and routes are configured correctly.
- SSH is reachable from an authorized administration path.
- The isolated network uses the intended gateway.
- Outbound connectivity matches the configured policy.
- Unintended inbound access is blocked.
- DNS records resolve to the expected destinations.
- Reverse-proxy routes reach their intended backends.
- Optional services are present only when selected.

Testing should include both isolated and home-network deployments, as well as adding, updating, and removing a host.

## 11. Architectural decisions

These decisions were approved on 2026-10-28. The implementation steps are in [PLAN.md](PLAN.md).

1. **Network configuration schema:** One file per network, `networks/<name>.yaml`, with a `network:` block and a `hosts:` list. Each host type's defaults are in its role's `defaults/main.yml`.
2. **Network identity:** Each network file spells out its bridge, CIDR, gateway and router. The router VM is a host in the list with `type: router`. Validation rejects two networks that share a bridge or a subnet.
3. **IP allocation:** Static addresses, written to the guest's `network.nix`. New clones boot on the template's address and then move to their own. The template address is reserved in the home network file.
4. **Firewall implementation:** The existing NixOS router (nftables, NAT, dnsmasq), with its settings taken from the network file.
5. **Host lifecycle interface:** Every declared host is added to the Ansible inventory. A play over the network's hosts runs with `serial: 1`, calls the Proxmox API from the workstation, and includes the role named by the host's type. Roles receive a normalized `host` dict and `network` dict. Deploying one host is the same play limited to that host. Running one host at a time also keeps two new clones from sharing the template's address.
6. **Deletion policy:** Removing a host from a network file never deletes it. A deploy reports VMs that the project owns but the file no longer lists. Deleting them needs `-e prune=true` and typing the network name. `destroy-network.yaml` deletes in reverse order: hosts, then the router, then (optionally) the bridge.
7. **Shared services:** Internal DNS runs on the router's dnsmasq. The reverse proxy is its own host type.
8. **Service dependencies:** The order is implied: bridge, router, then hosts in list order. Validation checks that every reverse-proxy backend and port forward points at a declared host. Explicit `depends_on` is added only if it becomes necessary.
9. **Internal DNS and TLS:** dnsmasq `address=` records built from the host list. Internal HTTP is plain at first. TLS comes with the reverse proxy, using Caddy's internal CA.
10. **State tracking:** Managed VMs carry Proxmox tags: `nixlab`, `net-<name>` and `type-<type>`. VMs that existed before tagging are adopted once, only when both their ID and name match the configuration. Every deploy also records the VM's current address in Proxmox. That's how a VM is found after its entry moves to another network file, since the files only hold where it should be. Before changing a VM, the playbook checks that the guest's `ens18` MAC matches `net0` in Proxmox. All clones share the template's SSH host key, so without this check a reused address could lead to reconfiguring the wrong VM. Reading addresses through the QEMU guest agent is a possible later improvement.
11. **Proxmox resource ownership:** The project creates and manages isolated bridges. It uses the home bridge (`vmbr0`) as it is. Nothing without the project's tags is ever deleted.
12. **Secrets management:** Per-host files at `secrets/<network>/<host>.env`, kept out of git. Ansible Vault or sops can replace them later.

## 12. Guidance for implementation

Before modifying the project:

1. Inspect the existing repository, playbooks, templates, variables, and VM lifecycle operations.
2. Identify which responsibilities are already implemented and which need to be added.
3. Map the current implementation to the architectural responsibilities defined here.
4. Propose the final configuration schema and orchestration interfaces.
5. Identify destructive operations, shared-resource ownership, and migration risks.
6. Present an incremental implementation plan for review.

Prefer extending working components over replacing them unnecessarily. Keep changes small enough to validate, and update this document when an approved architectural decision changes.

The objective is a reusable system for defining and deploying Proxmox lab networks through configuration, with consistent host lifecycle management and predictable networking behavior.