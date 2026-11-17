# roles/openbao/files/configuration.nix
#
# Installed to /etc/nixos on the openbao VM by roles/openbao, next to
# common.nix, network.nix (hostname and static IP) and openbao.nix (listener,
# API address, UI and firewall), which are generated from the host's network
# file entry.

{ config, lib, pkgs, ... }:

let
  dataDir = "/var/lib/openbao";
in
{
  imports = [
    ./hardware-configuration.nix
    ./common.nix
    ./network.nix
    ./openbao.nix
  ];

  # The module provides the systemd unit and its hardening. It doesn't
  # restart OpenBao on a switch, because a restart seals it; roles/openbao
  # restarts it when its configuration changes, then unseals it.
  services.openbao = {
    enable = true;
    settings = {
      # Integrated storage, on the data disk. A single node.
      storage.raft = {
        path = dataDir;
        node_id = config.networking.hostName;
      };
      # Recommended with raft storage, which keeps its data memory-mapped.
      # The unit already turns off swap for the service.
      disable_mlock = true;
    };
  };

  # The module runs OpenBao as a throwaway user by default, which doesn't
  # work with a mounted state folder. Use a fixed user instead, and keep the
  # protections that DynamicUser would have added.
  users.users.openbao = {
    isSystemUser = true;
    group = "openbao";
  };
  users.groups.openbao = { };

  systemd.services.openbao = {
    requires = [ "var-lib-openbao.mount" ];
    after = [ "var-lib-openbao.mount" ];
    serviceConfig = {
      # The module sets this to true, so it has to be forced off.
      DynamicUser = lib.mkForce false;
      User = "openbao";
      Group = "openbao";
      ProtectSystem = "strict";
      PrivateTmp = true;
      NoNewPrivileges = true;
      RestrictSUIDSGID = true;
      RemoveIPC = true;
    };
  };

  # OpenBao's encrypted storage lives on the separate data disk (scsi1,
  # serial "openbao-data"), which roles/openbao formats.
  # nofail keeps the VM bootable over SSH if the disk is missing; OpenBao
  # then refuses to start instead of starting over on the root disk.
  fileSystems.${dataDir} = {
    device = "/dev/disk/by-id/scsi-0QEMU_QEMU_HARDDISK_openbao-data";
    fsType = "ext4";
    options = [ "nofail" ];
  };
}
