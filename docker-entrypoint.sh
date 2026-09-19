#!/usr/bin/env bash
set -e

cd /workspace

git config --global --add safe.directory /workspace

git -C "/workspace" add "flake.nix"

exec bash

# nix flake check
# nix build .#nixosConfigurations.nixos-lab-01.config.system.build.toplevel