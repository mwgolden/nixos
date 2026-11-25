# roles/gitea_runner/files/configuration.nix
#
# Installed to /etc/nixos on the gitea_runner VM by roles/gitea_runner, next
# to common.nix, network.nix (hostname and static IP) and gitea_runner.nix
# (the runner, its labels, Docker and the data disk), which are generated
# from the host's network file entry.

{ config, pkgs, ... }:

{
  imports = [
    ./hardware-configuration.nix
    ./common.nix
    ./network.nix
    ./gitea_runner.nix
  ];

  # Gitea's act_runner, which the services.gitea-actions-runner module runs
  # as a systemd service (gitea-runner-default) under its own dynamic user.
  # It registers with Gitea on its first start, keeping the registration in
  # /var/lib/gitea-runner/default/.runner.
  services.gitea-actions-runner.package = pkgs.gitea-actions-runner;
}
