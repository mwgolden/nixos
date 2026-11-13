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
  # settings.packages in the network file. acl lets the deploy run tasks
  # as the user (Ansible needs setfacl to become an unprivileged user).
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
    acl
  ];

  # Lets prebuilt Linux programs run: Python wheels with compiled code,
  # the Pythons uv downloads, and native installers such as Claude Code's.
  # Add a library here if a tool fails with a missing .so file.
  programs.nix-ld = {
    enable = true;
    libraries = with pkgs; [
      stdenv.cc.cc.lib
      zlib
      openssl
    ];
  };

  # Every shell, including `ssh host command` and VS Code Remote-SSH,
  # loads the variables the deploy writes for the user (settings.environment,
  # the secrets file, and PATH for tools in their home). This ends up in
  # /etc/set-environment, which /etc/profile and /etc/bashrc both source.
  environment.extraInit = ''
    if [ -r "$HOME/.config/nixlab/env" ]; then
      set -a
      . "$HOME/.config/nixlab/env"
      set +a
    fi
  '';

  # SSH (22) is opened automatically by services.openssh. Nothing else
  # listens.
  networking.firewall.allowedTCPPorts = [ ];
}
