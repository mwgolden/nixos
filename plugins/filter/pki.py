"""Filters for the internal certificate authority (docs/plans/completed/INTERNAL-CA.md).

An openbao host with settings.pki holds a root CA at pki/ and one
intermediate per network whose security.pki names it, at pki-<network>/.
Each host on such a network gets a certificate from its network's
intermediate at deploy (roles/nixos_base, tls-cert.yml). These filters
decide which networks, which names and whether a certificate is still good;
the roles do the talking. They run on this machine, which has the
cryptography package (it comes with Ansible).
"""

import datetime
import ipaddress

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

# The mount every PKI authority keeps its root in, and the prefix of each
# network's intermediate.
ROOT_MOUNT = "pki"
INTERMEDIATE_PREFIX = "pki-"
LOOPBACK = "127.0.0.1"


def _split(instance):
    network, _, name = instance.partition(".")
    return network, name


def pki_root_file(instance):
    """Where the root certificate of an openbao host (by host ID) is kept,
    relative to the repository: secrets/<network>/<host>-pki-root.crt. The
    one file your machines trust."""
    network, name = _split(instance)
    return f"secrets/{network}/{name}-pki-root.crt"


def pki_intermediate_file(instance, network):
    """Where a network's intermediate certificate from that openbao host is
    kept: secrets/<authority network>/<host>-pki-<network>.crt. Deploys
    compare hosts' certificates against it, without asking OpenBao."""
    auth_network, name = _split(instance)
    return f"secrets/{auth_network}/{name}-pki-{network}.crt"


def tls_cert_names(vm):
    """The names a host's TLS certificate is for: {common_name, dns, ip}.
    DNS: <name>.<domain>, and for a proxy every route's name. IP: its
    address, a router's upstream address too, and 127.0.0.1 for an openbao
    host (its own deploy talks to it there). Bare host names aren't
    included: they aren't under the network's domain, so the intermediate
    can't sign them."""
    net = vm["network"]
    dns = [f"{vm['name']}.{net['domain']}"]
    if vm["type"] == "proxy":
        dns += [r["fqdn"] for r in net.get("proxy_routes", [])]
    ips = [vm["ip"], vm["attach"]["ip"]] + ([LOOPBACK] if vm["type"] == "openbao" else [])
    dns, ips = list(dict.fromkeys(dns)), list(dict.fromkeys(ips))
    return {"common_name": dns[0], "dns": dns, "ip": ips}


def _ip_cidrs(inventory, network):
    """Addresses a network's intermediate may put in certificates: its LAN
    and DMZ, its router's upstream address, and loopback when it has an
    openbao host (see tls_cert_names). OpenBao can't put IP constraints in
    the CA certificate itself, so this is enforced when signing only."""
    net = inventory["networks"][network]
    cidrs = [net["cidr"]]
    if net.get("dmz"):
        cidrs.append(net["dmz"]["cidr"])
    if net.get("router_wan_ip"):
        cidrs.append(f"{net['router_wan_ip']}/32")
    if any(h["type"] == "openbao" and h["network"]["name"] == network for h in inventory["hosts"].values()):
        cidrs.append(f"{LOOPBACK}/32")
    return cidrs


def pki_networks(inventory, instance):
    """The intermediates an openbao host with settings.pki keeps: one per
    network whose security.pki is {provider: openbao, instance: <this>},
    sorted by network. Each: {network, mount, domain, ip_cidrs, file}, with
    file relative to the repository (pki_intermediate_file)."""
    result = []
    for name, net in sorted(inventory["networks"].items()):
        pki = net["security"]["pki"]
        if pki["provider"] == "openbao" and pki["instance"] == instance:
            result.append({
                "network": name,
                "mount": f"{INTERMEDIATE_PREFIX}{name}",
                "domain": net["domain"],
                "ip_cidrs": _ip_cidrs(inventory, name),
                "file": pki_intermediate_file(instance, name),
            })
    return result


def pki_stale_mounts(mounts, inventory, instance):
    """Intermediate mounts (pki-<network>/) an openbao host has that no
    network uses any more, from the keys of GET sys/mounts."""
    wanted = {n["mount"] for n in pki_networks(inventory, instance)}
    have = {m.rstrip("/") for m in mounts}
    return sorted(m for m in have if m.startswith(INTERMEDIATE_PREFIX) and m not in wanted)


def host_pki(inventory, vm):
    """Where a host's TLS certificate comes from, or {} when its network
    doesn't use an OpenBao PKI: {instance, mount, root_file,
    intermediate_file}."""
    pki = vm["network"]["security"]["pki"]
    if pki["provider"] != "openbao" or not pki["instance"]:
        return {}
    network = vm["network"]["name"]
    return {
        "instance": pki["instance"],
        "mount": f"{INTERMEDIATE_PREFIX}{network}",
        "root_file": pki_root_file(pki["instance"]),
        "intermediate_file": pki_intermediate_file(pki["instance"], network),
    }


def _load(pem):
    if not pem or "BEGIN CERTIFICATE" not in pem:
        return None
    try:
        return x509.load_pem_x509_certificate(pem.encode() if isinstance(pem, str) else pem)
    except ValueError:
        return None


def _now(now):
    if now is None:
        return datetime.datetime.now(datetime.timezone.utc)
    if isinstance(now, str):
        return datetime.datetime.fromisoformat(now)
    return now


def _signed_by(cert, issuer):
    if cert.issuer != issuer.subject:
        return False
    key = issuer.public_key()
    try:
        if isinstance(key, ec.EllipticCurvePublicKey):
            key.verify(cert.signature, cert.tbs_certificate_bytes, ec.ECDSA(cert.signature_hash_algorithm))
        elif isinstance(key, rsa.RSAPublicKey):
            key.verify(cert.signature, cert.tbs_certificate_bytes, padding.PKCS1v15(), cert.signature_hash_algorithm)
        else:
            return False
    except Exception:  # noqa: BLE001 - any failure means "not signed by it"
        return False
    return True


def _sans(cert):
    try:
        ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except x509.ExtensionNotFound:
        return set(), set()
    return (set(ext.get_values_for_type(x509.DNSName)),
            {str(ip) for ip in ext.get_values_for_type(x509.IPAddress)})


def tls_cert_state(cert_pem, issuer_pem, names, renew_days=30, now=None):
    """Whether a host's certificate can stay: "keep", or why it needs a new
    one: "missing", "another CA" (not signed by issuer_pem, the network's
    current intermediate; also when that isn't known), "other names" (not
    exactly names' dns and ip), or "expiring" (fewer than renew_days left)."""
    cert = _load(cert_pem)
    if cert is None:
        return "missing"
    issuer = _load(issuer_pem)
    if issuer is None or not _signed_by(cert, issuer):
        return "another CA"
    dns, ips = _sans(cert)
    if dns != set(names["dns"]) or ips != {str(ipaddress.ip_address(i)) for i in names["ip"]}:
        return "other names"
    if cert.not_valid_after_utc - _now(now) < datetime.timedelta(days=int(renew_days)):
        return "expiring"
    return "keep"


def x509_days_left(pem, now=None):
    """Whole days until a certificate expires; -1 for no certificate."""
    cert = _load(pem)
    if cert is None:
        return -1
    return (cert.not_valid_after_utc - _now(now)).days


def x509_fingerprint(pem):
    """SHA-256 fingerprint of a certificate, as colon-separated hex; "" for
    none."""
    cert = _load(pem)
    if cert is None:
        return ""
    return cert.fingerprint(hashes.SHA256()).hex(":").upper()


def x509_permitted_dns(pem):
    """The permitted DNS names of a CA certificate's name constraints,
    sorted; [] when it has none."""
    cert = _load(pem)
    if cert is None:
        return []
    try:
        nc = cert.extensions.get_extension_for_class(x509.NameConstraints).value
    except x509.ExtensionNotFound:
        return []
    return sorted(n.value for n in nc.permitted_subtrees or [] if isinstance(n, x509.DNSName))


def x509_first(pem_bundle):
    """The first certificate of a PEM bundle (such as fullchain.pem), or ""."""
    marker = "-----END CERTIFICATE-----"
    if not pem_bundle or marker not in pem_bundle:
        return ""
    return pem_bundle[: pem_bundle.index(marker) + len(marker)] + "\n"


class FilterModule:
    def filters(self):
        return {
            "pki_root_file": pki_root_file,
            "pki_intermediate_file": pki_intermediate_file,
            "pki_networks": pki_networks,
            "pki_stale_mounts": pki_stale_mounts,
            "host_pki": host_pki,
            "tls_cert_names": tls_cert_names,
            "tls_cert_state": tls_cert_state,
            "x509_days_left": x509_days_left,
            "x509_fingerprint": x509_fingerprint,
            "x509_permitted_dns": x509_permitted_dns,
            "x509_first": x509_first,
        }
