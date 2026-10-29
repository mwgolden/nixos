# roles/router/files/configuration.nix
#
# Installed to /etc/nixos on the router by roles/router, next to common.nix,
# network.nix (hostname and WAN address) and router-vars.nix (LAN address,
# DHCP range, DNS servers and records, blocked networks, port forwards),
# generated from the network file.
#
# The router connects the isolated bridge to the internet:
#   WAN  ens18  Proxmox net0, on vmbr0 (the home LAN)
#   LAN  ens19  Proxmox net1, on the isolated bridge
#
# LAN clients get an address by DHCP and reach the internet through NAT.
# They can't reach private networks such as the home LAN, and on the router
# itself they can only use DHCP, DNS and ping. The home LAN can reach LAN
# VMs only through the port forwards in its network file.

{ config, lib, pkgs, ... }:

let
  vars = import ./router-vars.nix;
  wan = "ens18";
  lan = "ens19";
in
{
  imports = [
    ./hardware-configuration.nix
    ./common.nix
    ./network.nix
  ];

  networking.interfaces.${lan} = {
    useDHCP = false;
    ipv4.addresses = [{
      address = vars.lanAddress;
      prefixLength = vars.lanPrefixLength;
    }];
  };

  # The firewall and NAT below use nftables instead of iptables.
  networking.nftables.enable = true;

  # Masquerades LAN traffic leaving through the WAN. This also turns on IPv4
  # forwarding. IPv6 is not forwarded, so LAN clients have IPv4 only.
  networking.nat = {
    enable = true;
    externalInterface = wan;
    internalInterfaces = [ lan ];

    # Ports on the WAN address passed through to LAN VMs: the expose:
    # entries of the hosts in the network file. The firewall lets these in:
    # it accepts forwarded traffic that was redirected this way.
    forwardPorts = map (forward: {
      proto = forward.proto;
      sourcePort = forward.wanPort;
      destination = "${forward.lanAddress}:${toString forward.lanPort}";
    }) vars.portForwards;
  };

  networking.firewall = {
    enable = true;

    # Drop forwarded traffic unless a rule accepts it. Replies to
    # connections from the LAN are accepted automatically.
    filterForward = true;

    # The NAT module adds "accept LAN to WAN" to these rules. The home LAN is
    # also reached through the WAN, so the drop has to come first (mkBefore).
    extraForwardRules = lib.mkBefore ''
      iifname "${lan}" ip daddr { ${lib.concatStringsSep ", " vars.blockedNetworks} } counter drop comment "LAN may not reach private networks"
    '';

    # What LAN clients may use on the router: DHCP and DNS (ping is allowed
    # on every interface by default).
    interfaces.${lan} = {
      allowedUDPPorts = [ 53 67 ];
      allowedTCPPorts = [ 53 ];
    };

    # SSH only from the WAN side, not from the isolated LAN.
    interfaces.${wan}.allowedTCPPorts = [ 22 ];
  };

  services.openssh.openFirewall = false;

  # dig, for checking the DNS records below.
  environment.systemPackages = [ pkgs.dnsutils ];

  # DHCP and a DNS forwarder for the LAN.
  services.dnsmasq = {
    enable = true;
    # The router itself keeps using the nameserver from network.nix.
    resolveLocalQueries = false;

    settings = {
      interface = lan;
      # Listen only on the LAN, and pick up its address whenever it appears.
      bind-dynamic = true;

      # Forward queries to these servers instead of the router's own resolver.
      no-resolv = true;
      server = vars.dnsServers;
      domain-needed = true;
      bogus-priv = true;

      # Names for the network's hosts. Names in the domain are never
      # forwarded upstream, and DHCP clients get it as their search domain.
      domain = vars.domain;
      local = "/${vars.domain}/";
      host-record = map (r: "${r.name},${r.name}.${vars.domain},${r.ip}") vars.hostRecords;

      # The router and DNS options default to the router's LAN address.
      dhcp-range = [ "${vars.dhcpRangeStart},${vars.dhcpRangeEnd},${vars.dhcpLeaseTime}" ];
      dhcp-authoritative = true;
    };
  };
}
