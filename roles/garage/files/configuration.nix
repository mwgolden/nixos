# roles/garage/files/configuration.nix
#
# Installed to /etc/nixos on the garage VM by roles/garage, next to common.nix,
# network.nix (hostname and static IP) and garage.nix (S3 port, region and
# firewall), which are generated from the host's network file entry.

{ config, pkgs, ... }:

let
  dataDir = "/var/lib/garage";
  rpcSecretFile = "${dataDir}/rpc_secret";
in
{
  imports = [
    ./hardware-configuration.nix
    ./common.nix
    ./network.nix
    ./garage.nix
  ];

  services.garage = {
    enable = true;
    # Garage can only move up one major version at a time, so upgrades to a
    # newer garage_N package need care; see the NixOS manual's Garage section.
    package = pkgs.garage_2;
    settings = {
      # A single node keeps one copy of everything.
      replication_factor = 1;
      db_engine = "lmdb";
      metadata_dir = "${dataDir}/meta";
      data_dir = "${dataDir}/data";
      # Copies of the metadata database, in meta/snapshots, to recover from
      # if it is ever damaged.
      metadata_auto_snapshot_interval = "6h";

      # Nodes talk to each other over RPC. With only one node, this is just
      # how the garage command reaches the server, so it stays on loopback.
      rpc_bind_addr = "127.0.0.1:3901";
      rpc_public_addr = "127.0.0.1:3901";
      rpc_secret_file = rpcSecretFile;
    };
  };

  # The module runs Garage as a throwaway user by default, which doesn't
  # work with a mounted state folder. Use a fixed user instead.
  users.users.garage = {
    isSystemUser = true;
    group = "garage";
  };
  users.groups.garage = { };

  systemd.services.garage = {
    requires = [ "var-lib-garage.mount" "garage-data-dirs.service" ];
    after = [ "var-lib-garage.mount" "garage-data-dirs.service" ];
    serviceConfig = {
      DynamicUser = false;
      User = "garage";
      Group = "garage";
      StateDirectoryMode = "0700";
    };
  };

  # Everything Garage keeps (objects, metadata and the RPC secret) lives on
  # the separate data disk (scsi1, serial "garage-data"), which roles/garage
  # formats.
  # nofail keeps the VM bootable over SSH if the disk is missing; Garage then
  # refuses to start instead of writing to the root disk.
  fileSystems.${dataDir} = {
    device = "/dev/disk/by-id/scsi-0QEMU_QEMU_HARDDISK_garage-data";
    fsType = "ext4";
    options = [ "nofail" ];
  };

  # Creates Garage's folders on the mounted disk, and the RPC secret the
  # first time. The secret stays on the data disk, so it never ends up in
  # the Nix store or the repository.
  systemd.services.garage-data-dirs = {
    description = "Create Garage's folders and RPC secret on its data disk";
    requires = [ "var-lib-garage.mount" ];
    after = [ "var-lib-garage.mount" ];
    before = [ "garage.service" ];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    script = ''
      install -d -m 0700 -o garage -g garage ${dataDir} ${dataDir}/meta ${dataDir}/data
      if [ ! -s ${rpcSecretFile} ]; then
        (umask 077; ${pkgs.openssl}/bin/openssl rand -hex 32 > ${rpcSecretFile}.new)
        mv ${rpcSecretFile}.new ${rpcSecretFile}
      fi
      chown garage:garage ${rpcSecretFile}
      chmod 0600 ${rpcSecretFile}
    '';
  };
}
