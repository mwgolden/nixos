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
#   DMZ  ens20  Proxmox net2, on the DMZ bridge, when the network has a dmz:
#   VPN  wg0    WireGuard, when settings.vpn is set
#
# LAN clients get an address by DHCP and reach the internet through NAT.
# They can't reach private networks such as the home LAN, and on the router
# itself they can only use DHCP, DNS and ping. The home LAN can reach LAN
# VMs only through the port forwards in its network file.
#
# DMZ hosts are treated like LAN hosts, except that the LAN can reach them
# but they can't reach the LAN, apart from the ports in dmzRules.

{ config, lib, pkgs, ... }:

let
  vars = import ./router-vars.nix;
  wan = "ens18";
  lan = "ens19";
  vpn = "wg0";
  dmz = "ens20";

  # One accept per DMZ rule: this DMZ host to this LAN host and port.
  dmzRuleLines = lib.concatMapStrings (rule: ''
    iifname "${dmz}" oifname "${lan}" ip saddr ${rule.srcAddress} ip daddr ${rule.dstAddress} ${rule.proto} dport ${toString rule.port} accept comment "DMZ: ${rule.name}"
  '') vars.dmzRules;
  blocked = lib.concatStringsSep ", " vars.blockedNetworks;
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

  networking.interfaces.${dmz} = lib.mkIf vars.dmz.enable {
    useDHCP = false;
    ipv4.addresses = [{
      address = vars.dmz.address;
      prefixLength = vars.dmz.prefixLength;
    }];
  };

  # The firewall and NAT below use nftables instead of iptables.
  networking.nftables.enable = true;

  # Masquerades LAN traffic leaving through the WAN. This also turns on IPv4
  # forwarding. IPv6 is not forwarded, so LAN clients have IPv4 only.
  networking.nat = {
    enable = true;
    externalInterface = wan;
    internalInterfaces = [ lan ] ++ lib.optional vars.dmz.enable dmz;

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

    # The NAT module adds "accept LAN to WAN" (and DMZ to WAN) to these
    # rules. The home LAN is also reached through the WAN, so the drops have
    # to come first (mkBefore). The DMZ's subnet is a private network too,
    # so LAN to DMZ and the DMZ rules have to come before the drops.
    extraForwardRules = lib.mkBefore (lib.optionalString vars.dmz.enable (dmzRuleLines + ''
      iifname "${lan}" oifname "${dmz}" accept comment "LAN may reach the DMZ"
    '') + ''
      iifname "${lan}" ip daddr { ${blocked} } counter drop comment "LAN may not reach private networks"
    '' + lib.optionalString vars.dmz.enable ''
      iifname "${dmz}" ip daddr { ${blocked} } counter drop comment "DMZ may not reach private networks"
    '' + lib.optionalString vars.vpn.enable (''
      iifname "${vpn}" oifname "${lan}" accept comment "VPN clients may reach the LAN"
    '' + lib.optionalString vars.dmz.enable ''
      iifname "${vpn}" oifname "${dmz}" accept comment "VPN clients may reach the DMZ"
    ''));

    # What LAN clients may use on the router: DHCP and DNS (ping is allowed
    # on every interface by default).
    interfaces.${lan} = {
      allowedUDPPorts = [ 53 67 ];
      allowedTCPPorts = [ 53 ];
    };

    # What DMZ clients may use on the router: DNS, and DHCP when the DMZ
    # has a range. No SSH, as on the LAN.
    interfaces.${dmz} = lib.mkIf vars.dmz.enable {
      allowedUDPPorts = [ 53 ] ++ lib.optional vars.dmz.dhcp 67;
      allowedTCPPorts = [ 53 ];
    };

    # SSH only from the WAN side (and the VPN), not from the isolated LAN.
    interfaces.${wan} = {
      allowedTCPPorts = [ 22 ];
      allowedUDPPorts = lib.optional vars.vpn.enable vars.vpn.port;
    };

    # VPN clients may use DNS and SSH on the router.
    interfaces.${vpn} = lib.mkIf vars.vpn.enable {
      allowedUDPPorts = [ 53 ];
      allowedTCPPorts = [ 22 53 ];
    };
  };

  # VPN clients reach the LAN and the router; nothing else is routed for
  # them. Each peer may only use its own address.
  networking.wireguard.interfaces = lib.optionalAttrs vars.vpn.enable {
    ${vpn} = {
      ips = [ "${vars.vpn.address}/${toString vars.vpn.prefixLength}" ];
      listenPort = vars.vpn.port;
      privateKeyFile = "/var/lib/wireguard/wg0.key";
      peers = map (peer: {
        publicKey = peer.publicKey;
        allowedIPs = [ "${peer.ip}/32" ];
      }) vars.vpn.peers;
    };
  };

  services.openssh.openFirewall = false;

  # dig, for checking the DNS records below, and wg, for the VPN.
  environment.systemPackages = [ pkgs.dnsutils ] ++ lib.optional vars.vpn.enable pkgs.wireguard-tools;

  # DHCP and a DNS forwarder for the LAN.
  services.dnsmasq = {
    enable = true;
    # The router itself keeps using the nameserver from network.nix.
    resolveLocalQueries = false;

    settings = {
      # DMZ and VPN clients use it for DNS too. DHCP is served on the LAN,
      # and on the DMZ only when it has a range.
      interface = [ lan ] ++ lib.optional vars.dmz.enable dmz ++ lib.optional vars.vpn.enable vpn;
      no-dhcp-interface = lib.optional (vars.dmz.enable && !vars.dmz.dhcp) dmz
        ++ lib.optional vars.vpn.enable vpn;
      # Listen only on these interfaces, and pick up their addresses whenever they appear.
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

      # The router and DNS options default to the address of the interface
      # the request came in on.
      dhcp-range = [ "${vars.dhcpRangeStart},${vars.dhcpRangeEnd},${vars.dhcpLeaseTime}" ]
        ++ lib.optional (vars.dmz.enable && vars.dmz.dhcp)
          "${vars.dmz.dhcpRangeStart},${vars.dmz.dhcpRangeEnd},${vars.dmz.dhcpLeaseTime}";
      dhcp-authoritative = true;
    };
  };
}
