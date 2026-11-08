# roles/workstation/files/configuration.nix
#
# Installed to /etc/nixos on the workstation VM by roles/workstation, next
# to common.nix, network.nix (hostname and static IP) and workstation.nix
# (the user account), which are generated from the host's network file
# entry.

{ config, pkgs, ... }:

{
  imports = [
    ./hardware-configuration.nix
    ./common.nix
    ./network.nix
    ./workstation.nix
  ];

  # Accounts and passwords come only from the configuration, so changing
  # or removing the user's password or keys and redeploying applies it.
  # The user can't change their own password with passwd.
  users.mutableUsers = false;

  # Keys only over SSH. A password, if set, is for the Proxmox console.
  services.openssh.settings = {
    PasswordAuthentication = false;
    KbdInteractiveAuthentication = false;
  };

  # Tools for everyone on the VM. Add more for the user alone with
  # settings.packages in the network file.
  environment.systemPackages = with pkgs; [
    curl
    wget
    vim
    tmux
    htop
    jq
    ripgrep
    tree
    unzip
  ];

  # SSH (22) is opened automatically by services.openssh. Nothing else
  # listens.
  networking.firewall.allowedTCPPorts = [ ];
}
