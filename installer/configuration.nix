{ config, pkgs, modulesPath, ... }:

{
  imports = [
    "${modulesPath}/installer/cd-dvd/installation-cd-minimal.nix"
  ];

  environment.systemPackages = with pkgs; [
      python3
      git
  ];

  networking.interfaces.ens18.ipv4.addresses = [{
    address = "192.168.1.10";
    prefixLength = 24;
  }];

  networking.defaultGateway = "192.168.1.1";

  networking.nameservers = [
    "192.168.1.1"
  ];
  
  services.openssh.enable = true;

  systemd.services.sshd.wantedBy = pkgs.lib.mkForce [ "multi-user.target" ];

  users.users.root.openssh.authorizedKeys.keys = [
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMSE+JTfGnTV5FuH4nj1+9daykK+J7D+9zq0vxkpmm6H nixos-installer"
  ];
}