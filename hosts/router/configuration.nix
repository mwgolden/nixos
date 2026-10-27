# hosts/router/configuration.nix
#
# Installed to /etc/nixos on the router by router.yaml, next to common.nix,
# network.nix (hostname and WAN address) and router-vars.nix (LAN address,
# DHCP range, DNS servers, blocked networks), generated from vars.yaml.
#
# The router connects the isolated bridge to the internet:
#   WAN  ens18  Proxmox net0, on vmbr0 (the home LAN)
#   LAN  ens19  Proxmox net1, on the isolated bridge
#
# LAN clients get an address by DHCP and reach the internet through NAT.
# They can't reach private networks such as the home LAN, and on the router
# itself they can only use DHCP, DNS and ping.

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

      # The router and DNS options default to the router's LAN address.
      dhcp-range = [ "${vars.dhcpRangeStart},${vars.dhcpRangeEnd},${vars.dhcpLeaseTime}" ];
      dhcp-authoritative = true;
    };
  };
}
