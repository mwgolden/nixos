FROM debian:bookworm

ARG UID=1000
ARG GID=1000

RUN apt-get update \
    && apt-get install -y \
        curl \
        git \
        ca-certificates \
        xz-utils \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid ${GID} nixuser \
    && useradd --uid ${UID} --gid ${GID} --create-home --shell /bin/bash nixuser \
    && mkdir -m 0755 /nix \
    && chown nixuser:nixuser /nix

USER nixuser

ENV USER=nixuser
ENV PATH=/home/nixuser/.nix-profile/bin:$PATH

# Enable Nix experimental features
RUN mkdir -p /home/nixuser/.config/nix \
    && printf '%s\n' \
        'experimental-features = nix-command flakes' \
        > /home/nixuser/.config/nix/nix.conf

# Install Nix at image build time so containers start ready to use.
RUN curl -fsSL https://nixos.org/nix/install -o /tmp/nix-install \
    && sh /tmp/nix-install --no-daemon \
    && rm /tmp/nix-install \
    && nix profile install nixpkgs#nixos-rebuild

COPY --chmod=0755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

WORKDIR /workspace

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["bash"]
