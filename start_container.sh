docker build \
  --build-arg UID="$(id -u)" \
  --build-arg GID="$(id -g)" \
  -t nixos-lab .

docker run --rm -it \
  -v "$(pwd):/workspace" \
  nixos-lab