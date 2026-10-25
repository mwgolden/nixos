#!/usr/bin/env bash
# Open an interactive shell in the Nix build container.
# To build the installer ISO from inside it:
#   nix build --impure .#nixosConfigurations.installer.config.system.build.isoImage
# (needs NIXOS_INSTALLER_AUTHORIZED_KEY set; bootstrap.sh does all of this for you)
set -euo pipefail

cd "$(dirname "$0")"

if [ -z "${NIXOS_INSTALLER_AUTHORIZED_KEY:-}" ] && [ -n "${NIXOS_INSTALLER_PUBLIC_KEY:-}" ]; then
  NIXOS_INSTALLER_AUTHORIZED_KEY="$(cat "$NIXOS_INSTALLER_PUBLIC_KEY")"
fi

docker build \
  --build-arg UID="$(id -u)" \
  --build-arg GID="$(id -g)" \
  -t nixos-lab .

docker run --rm -it \
  -v "$(pwd):/workspace" \
  -e NIXOS_INSTALLER_AUTHORIZED_KEY="${NIXOS_INSTALLER_AUTHORIZED_KEY:-}" \
  nixos-lab
