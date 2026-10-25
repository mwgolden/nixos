{ config, lib, pkgs, modulesPath, ... }:

let
  # Public key allowed to SSH in as root on the installer. Read from the
  # environment at build time, so the build needs `--impure`.
  # bootstrap.sh sets this from the file in NIXOS_INSTALLER_PUBLIC_KEY.
  installerKey = builtins.getEnv "NIXOS_INSTALLER_AUTHORIZED_KEY";
in
{
  imports = [
    "${modulesPath}/installer/cd-dvd/installation-cd-minimal.nix"
  ];

  assertions = [{
    assertion = installerKey != "";
    message = "NIXOS_INSTALLER_AUTHORIZED_KEY is empty. Set it to the installer SSH public key and build with --impure.";
  }];

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

  systemd.services.sshd.wantedBy = lib.mkForce [ "multi-user.target" ];

  users.users.root.openssh.authorizedKeys.keys = lib.optional (installerKey != "") installerKey;
}
