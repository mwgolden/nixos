# roles/webserver/files/configuration.nix
#
# Installed to /etc/nixos on the webserver by roles/webserver, next to
# common.nix and network.nix (hostname and static IP, generated from the host's network file entry).

{ config, pkgs, ... }:

{
  imports = [
    ./hardware-configuration.nix
    ./common.nix
    ./network.nix
  ];

  services.nginx = {
    enable = true;

    virtualHosts."_" = {
      default = true;
      root = "/var/www";
    };
  };

  # Site files are copied here from files/site/ by roles/webserver.
  systemd.tmpfiles.rules = [
    "d /var/www 0755 root root -"
  ];

  # SSH (22) is opened automatically by services.openssh.
  networking.firewall.allowedTCPPorts = [ 80 ];
}
