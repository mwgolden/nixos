#!/usr/bin/env bash
# Build the NixOS installer ISO in Docker, upload it to Proxmox and turn
# VM 110 into a NixOS template.
#
# Usage: ./bootstrap.sh [--force] [-- <extra ansible-playbook args>]
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: ./bootstrap.sh [--force] [-- <extra ansible-playbook args>]

  --force   Destroy VM 110 first if it already exists.
  --        Pass the remaining arguments to ansible-playbook (e.g. -- -vv).

Settings are read from the environment, or from proxmox/.env if present.
EOF
}

die() { echo "error: $*" >&2; exit 1; }
step() { printf '\n==> %s\n' "$*"; }

force=false
ansible_args=()
while [ $# -gt 0 ]; do
  case "$1" in
    --force) force=true ;;
    -h|--help) usage; exit 0 ;;
    --) shift; ansible_args=("$@"); break ;;
    *) usage >&2; exit 2 ;;
  esac
  shift
done

repo_root="$(cd "$(dirname "$0")" && pwd)"
cd "$repo_root"

if [ -f proxmox/.env ]; then
  # shellcheck disable=SC1091
  source proxmox/.env
fi

# Prefer the project's Ansible install when there is one.
if [ -x .venv/bin/ansible-playbook ]; then
  PATH="$repo_root/.venv/bin:$PATH"
fi

step "Checking prerequisites"
for cmd in docker ansible-playbook ansible-galaxy; do
  command -v "$cmd" >/dev/null || die "'$cmd' not found"
done
docker info >/dev/null 2>&1 || die "cannot reach the Docker daemon"

for var in PROXMOX_TOKEN_SECRET NIXOS_INSTALLER_KEY NIXOS_INSTALLER_PUBLIC_KEY \
           NIXOS_DEPLOYMENT_PUBLIC_KEY NIXOS_DEPLOYMENT_PRIVATE_KEY; do
  [ -n "${!var:-}" ] || die "$var is not set (see README)"
done
for var in NIXOS_INSTALLER_KEY NIXOS_INSTALLER_PUBLIC_KEY \
           NIXOS_DEPLOYMENT_PUBLIC_KEY NIXOS_DEPLOYMENT_PRIVATE_KEY; do
  [ -r "${!var}" ] || die "$var points to a missing file: ${!var}"
done

# Python libraries the Proxmox modules need. requests_toolbelt is only used
# for uploads over 256 MB, which includes the ISO.
ansible_python="$(head -n 1 "$(command -v ansible-playbook)" | sed 's/^#!//')"
for module in proxmoxer requests requests_toolbelt; do
  $ansible_python -I -c "import $module" 2>/dev/null \
    || die "Python library $module is missing for Ansible ($ansible_python)"
done

for collection in community.proxmox community.general ansible.posix; do
  ansible-galaxy collection list "$collection" 2>/dev/null | grep -q "^$collection " \
    || die "Ansible collection $collection is not installed"
done

step "Building the Nix container image"
docker build \
  --build-arg UID="$(id -u)" \
  --build-arg GID="$(id -g)" \
  -t nixos-lab .

# Keep the Nix store in a volume so later builds reuse it. The volume is tied
# to the image ID, because a rebuilt image has its own Nix install.
image_id="$(docker image inspect -f '{{.Id}}' nixos-lab | cut -d: -f2 | cut -c1-12)"
nix_volume="nixos-lab-nix-$image_id"

step "Building the installer ISO"
mkdir -p build
iso_name="$(
  docker run --rm \
    -v "$repo_root:/workspace" \
    -v "$nix_volume:/nix" \
    -e NIXOS_INSTALLER_AUTHORIZED_KEY="$(cat "$NIXOS_INSTALLER_PUBLIC_KEY")" \
    nixos-lab \
    bash -euo pipefail -c '
      out="$(nix build --impure --no-link --print-out-paths \
        .#nixosConfigurations.installer.config.system.build.isoImage)"
      iso="$(find "$out/iso" -name "*.iso" | head -n 1)"
      [ -n "$iso" ] || { echo "no ISO found in $out/iso" >&2; exit 1; }
      # Name the ISO after its store hash so each build gets a unique name.
      name="nixos-installer-$(basename "$out" | cut -c1-12).iso"
      if [ ! -f "build/$name" ]; then
        cp "$iso" "build/$name"
        chmod 0644 "build/$name"
      fi
      echo "$name"
    '
)"
echo "Installer ISO: build/$iso_name"

step "Uploading the ISO and building the Proxmox template"
ansible-playbook proxmox/bootstrap.yaml \
  -e "{\"installer_iso\": \"$repo_root/build/$iso_name\", \"force_recreate\": $force}" \
  "${ansible_args[@]}"

step "Done: VM 110 is now a NixOS template"
