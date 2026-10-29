# roles/proxy/files/configuration.nix
#
# Installed to /etc/nixos on the proxy by roles/proxy, next to common.nix,
# network.nix (hostname and static IP) and proxy.nix (one site per route),
# which are generated from the network file.
#
# Caddy serves each route over HTTPS with a certificate from its own
# certificate authority ("tls internal"), and redirects HTTP to HTTPS. The
# authority's root certificate is in Caddy's data directory; roles/proxy
# copies it to secrets/<network>/<host>-ca.crt.

{ config, pkgs, ... }:

{
  imports = [
    ./hardware-configuration.nix
    ./common.nix
    ./network.nix
    ./proxy.nix
  ];

  services.caddy.enable = true;

  # curl, for roles/proxy to check each route from the VM itself.
  environment.systemPackages = [ pkgs.curl ];

  # SSH (22) is opened automatically by services.openssh.
  networking.firewall.allowedTCPPorts = [ 80 443 ];
}
