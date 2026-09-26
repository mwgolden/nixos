# modules/common.nix

{ config, lib, pkgs, ... }:

{
  environment.systemPackages = with pkgs; [
              python3
              git
          ];

  # Use the GRUB 2 boot loader.
  boot.loader.grub.enable = true;
  # boot.loader.grub.efiSupport = true;
  # boot.loader.grub.efiInstallAsRemovable = true;
  # boot.loader.efi.efiSysMountPoint = "/boot/efi";
  # Define on which hard drive you want to install Grub.
  boot.loader.grub.device = "/dev/sda"; # or "nodev" for efi only

  services.openssh.enable = true;

  users.users.admin = {
    isNormalUser = true;
    extraGroups = [ "wheel" ];

    openssh.authorizedKeys.keys = [
      "{{ lookup('file', lookup('env', 'NIXOS_DEPLOYMENT_PUBLIC_KEY')) }}"
    ];
  };

  security.sudo.wheelNeedsPassword = false;
}