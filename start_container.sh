docker build -t nixos-lab .

docker run --rm -it \
  -v "$(pwd):/workspace" \
  nixos-lab