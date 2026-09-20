#!/usr/bin/env bash
set -e

if [ ! -x "$HOME/.nix-profile/bin/nix" ]; then
    echo "Installing Nix..."
    sh <(curl -L https://nixos.org/nix/install) --no-daemon
fi

export PATH="$HOME/.nix-profile/bin:$PATH"

if ! command -v nixos-rebuild >/dev/null 2>&1; then
    echo "Installing nixos-rebuild..."
    nix profile install nixpkgs#nixos-rebuild
fi

cd /workspace

git config --global --add safe.directory /workspace

exec bash

# nix flake check
# nix build .#nixosConfigurations.nixos-lab-01.config.system.build.toplevel