FROM nixos/nix:2.28.3

RUN echo "experimental-features = nix-command flakes" >> /etc/nix/nix.conf

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

WORKDIR /workspace

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]