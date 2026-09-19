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

# Enable Nix experimental features
RUN mkdir -p /home/nixuser/.config/nix \
    && printf '%s\n' \
        'experimental-features = nix-command flakes' \
        > /home/nixuser/.config/nix/nix.conf \
    && chown -R nixuser:nixuser /home/nixuser/.config

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN chmod +x /usr/local/bin/docker-entrypoint.sh

USER nixuser

WORKDIR /workspace

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]