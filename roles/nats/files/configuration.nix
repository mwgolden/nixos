# roles/nats/files/configuration.nix
#
# Installed to /etc/nixos on the nats VM by roles/nats, next to common.nix,
# network.nix (hostname and static IP) and nats.nix (the NATS server
# configuration and firewall), which are generated from the host's network
# file entry.

{ config, pkgs, ... }:

let
  dataDir = "/var/lib/nats";
in
{
  imports = [
    ./hardware-configuration.nix
    ./common.nix
    ./network.nix
    ./nats.nix
  ];

  # The module provides the nats user, the systemd unit and its hardening.
  # nats.nix replaces the module's configuration file with its own, which
  # can read the client login from the environment.
  services.nats = {
    enable = true;
    jetstream = true;
    inherit dataDir;
  };

  systemd.services.nats = {
    requires = [ "var-lib-nats.mount" ];
    after = [ "var-lib-nats.mount" ];
    # NATS_USER and NATS_PASSWORD, written by roles/nats. Kept out of the
    # Nix store, which every user on the VM can read.
    serviceConfig.EnvironmentFile = "/etc/nats/nats.env";
  };

  # JetStream's streams live on the separate data disk (scsi1, serial
  # "nats-data"), which roles/nats formats.
  # nofail keeps the VM bootable over SSH if the disk is missing; NATS then
  # refuses to start instead of writing to the root disk.
  fileSystems.${dataDir} = {
    device = "/dev/disk/by-id/scsi-0QEMU_QEMU_HARDDISK_nats-data";
    fsType = "ext4";
    options = [ "nofail" ];
  };
}
