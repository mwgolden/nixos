"""Tests for the internal CA's filters (plugins/filter/pki.py,
docs/plans/completed/INTERNAL-CA.md).

    .venv/bin/python -m unittest discover -s tests
"""

import copy
import datetime
import importlib.util
import ipaddress
import pathlib
import unittest

import yaml
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "plugins" / "filter" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


nc = load("network_config")
pki = load("pki")

REPO_FILES = [{"file": p.stem, "config": yaml.safe_load(p.read_text())}
              for p in sorted((ROOT / "networks").glob("*.yaml"))]
NOW = datetime.datetime(2026, 11, 21, tzinfo=datetime.timezone.utc)


def files_with_pki():
    """home's openbao is the root; lab and home use it."""
    files = copy.deepcopy(REPO_FILES)
    by_name = {f["file"]: f["config"] for f in files}
    for f in files:
        f["config"]["network"].pop("security", None)
        for h in f["config"].get("hosts") or []:
            if h["type"] == "openbao" and (h.get("settings") or {}).get("tls") == "pki":
                h["settings"]["tls"] = "self-signed"
    bao = next(h for h in by_name["home"]["hosts"] if h["type"] == "openbao")
    bao["settings"] = {"tls": "pki", "ssh_user_ca": True, "pki": True}
    by_name["home"]["network"]["security"] = {
        "strategy": "centralized", "secrets": {"provider": "files"},
        "administrative_identity": {"instance": "home.openbao"},
        "pki": {"provider": "openbao", "instance": "home.openbao"}}
    by_name["lab"]["network"]["security"] = {"pki": {"provider": "openbao", "instance": "home.openbao"}}
    return files


def inventory(files):
    return nc.network_config_inventory({f["file"]: f["config"] for f in files})


# ---- Certificates for tls_cert_state ----

def _name(cn):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def make_ca(cn, issuer=None, issuer_key=None):
    key = ec.generate_private_key(ec.SECP256R1())
    builder = (x509.CertificateBuilder().subject_name(_name(cn))
               .issuer_name(issuer.subject if issuer else _name(cn))
               .public_key(key.public_key()).serial_number(x509.random_serial_number())
               .not_valid_before(NOW - datetime.timedelta(days=1))
               .not_valid_after(NOW + datetime.timedelta(days=1800))
               .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
               .add_extension(x509.NameConstraints(permitted_subtrees=[x509.DNSName("lab.home.arpa")],
                                                   excluded_subtrees=None), critical=True))
    cert = builder.sign(issuer_key or key, hashes.SHA256())
    return cert, key


def make_leaf(issuer, issuer_key, dns, ips, days):
    key = ec.generate_private_key(ec.SECP256R1())
    sans = [x509.DNSName(d) for d in dns] + [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
    cert = (x509.CertificateBuilder().subject_name(_name(dns[0])).issuer_name(issuer.subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(NOW - datetime.timedelta(days=1))
            .not_valid_after(NOW + datetime.timedelta(days=days))
            .add_extension(x509.SubjectAlternativeName(sans), critical=False)
            .sign(issuer_key, hashes.SHA256()))
    return cert


def pem(cert):
    return cert.public_bytes(serialization.Encoding.PEM).decode()


class Names(unittest.TestCase):
    def setUp(self):
        self.inv = inventory(files_with_pki())

    def test_plain_host(self):
        self.assertEqual(pki.tls_cert_names(self.inv["hosts"]["lab.gitea"]),
                         {"common_name": "gitea.lab.home.arpa", "dns": ["gitea.lab.home.arpa"], "ip": ["10.1.0.14"]})

    def test_router_has_its_upstream_address(self):
        self.assertEqual(pki.tls_cert_names(self.inv["hosts"]["lab.router"])["ip"], ["10.1.0.1", "192.168.1.13"])

    def test_proxy_has_its_routes(self):
        names = pki.tls_cert_names(self.inv["hosts"]["lab.proxy"])
        self.assertEqual(names["dns"][0], "proxy.lab.home.arpa")
        self.assertIn("git.lab.home.arpa", names["dns"])
        self.assertEqual(len(names["dns"]), 1 + len(self.inv["networks"]["lab"]["proxy_routes"]))

    def test_openbao_has_loopback(self):
        self.assertEqual(pki.tls_cert_names(self.inv["hosts"]["home.openbao"]),
                         {"common_name": "openbao.home.home.arpa", "dns": ["openbao.home.home.arpa"],
                          "ip": ["192.168.1.20", "127.0.0.1"]})


class Networks(unittest.TestCase):
    def setUp(self):
        self.inv = inventory(files_with_pki())

    def test_files_are_valid(self):
        self.assertEqual(nc.network_config_errors(files_with_pki(), 110, "192.168.1.10"), [])

    def test_intermediates(self):
        nets = pki.pki_networks(self.inv, "home.openbao")
        self.assertEqual([n["network"] for n in nets], ["home", "lab"])
        lab = nets[1]
        self.assertEqual(lab["mount"], "pki-lab")
        self.assertEqual(lab["domain"], "lab.home.arpa")
        self.assertEqual(lab["file"], "secrets/home/openbao-pki-lab.crt")
        self.assertEqual(lab["ip_cidrs"], ["10.1.0.0/24", "10.1.1.0/24", "192.168.1.13/32"])
        self.assertEqual(nets[0]["ip_cidrs"], ["192.168.1.0/24", "127.0.0.1/32"])

    def test_no_intermediates_elsewhere(self):
        self.assertEqual(pki.pki_networks(self.inv, "agent-developer.openbao"), [])

    def test_host_pki(self):
        self.assertEqual(pki.host_pki(self.inv, self.inv["hosts"]["lab.gitea"]), {
            "instance": "home.openbao", "mount": "pki-lab",
            "root_file": "secrets/home/openbao-pki-root.crt",
            "intermediate_file": "secrets/home/openbao-pki-lab.crt"})
        self.assertEqual(pki.host_pki(self.inv, self.inv["hosts"]["workstation-lab.gitea"]), {})

    def test_stale_mounts(self):
        mounts = ["pki/", "pki-lab/", "pki-old/", "secret/", "sys/"]
        self.assertEqual(pki.pki_stale_mounts(mounts, self.inv, "home.openbao"), ["pki-old"])


class CertState(unittest.TestCase):
    def setUp(self):
        self.ca, self.ca_key = make_ca("nixlab lab")
        self.names = {"dns": ["gitea.lab.home.arpa"], "ip": ["10.1.0.14"]}

    def leaf(self, dns=("gitea.lab.home.arpa",), ips=("10.1.0.14",), days=365, ca=None, key=None):
        return pem(make_leaf(ca or self.ca, key or self.ca_key, list(dns), list(ips), days))

    def state(self, cert, issuer=None):
        return pki.tls_cert_state(cert, pem(issuer or self.ca), self.names, 30, NOW)

    def test_keep(self):
        self.assertEqual(self.state(self.leaf()), "keep")

    def test_fullchain_counts_as_its_leaf(self):
        self.assertEqual(self.state(self.leaf() + pem(self.ca)), "keep")

    def test_missing(self):
        self.assertEqual(self.state(""), "missing")

    def test_another_ca(self):
        other, other_key = make_ca("nixlab lab")  # same name, other key
        self.assertEqual(self.state(self.leaf(ca=other, key=other_key)), "another CA")
        self.assertEqual(pki.tls_cert_state(self.leaf(), "", self.names, 30, NOW), "another CA")

    def test_other_names(self):
        self.assertEqual(self.state(self.leaf(ips=("10.1.0.15",))), "other names")
        self.assertEqual(self.state(self.leaf(dns=("gitea.lab.home.arpa", "git.lab.home.arpa"))), "other names")

    def test_expiring(self):
        self.assertEqual(self.state(self.leaf(days=29)), "expiring")
        self.assertEqual(self.state(self.leaf(days=31)), "keep")

    def test_x509_helpers(self):
        self.assertEqual(pki.x509_days_left(pem(self.ca), NOW), 1800)
        self.assertEqual(pki.x509_days_left("", NOW), -1)
        self.assertEqual(pki.x509_permitted_dns(pem(self.ca)), ["lab.home.arpa"])
        self.assertEqual(pki.x509_permitted_dns(self.leaf()), [])
        self.assertEqual(len(pki.x509_fingerprint(pem(self.ca)).split(":")), 32)
        self.assertNotEqual(pki.x509_fingerprint(pem(self.ca)), pki.x509_fingerprint(self.leaf()))
        leaf = self.leaf()
        self.assertEqual(pki.x509_first(leaf + pem(self.ca)), leaf)



class RepoFiles(unittest.TestCase):
    """What the repository's own network files declare."""

    def test_every_network_uses_the_home_root(self):
        inv = inventory(copy.deepcopy(REPO_FILES))
        self.assertEqual([n["network"] for n in pki.pki_networks(inv, "home.openbao")],
                         sorted(inv["networks"]))

    def test_every_host_gets_a_certificate(self):
        inv = inventory(copy.deepcopy(REPO_FILES))
        for vm in inv["hosts"].values():
            with self.subTest(host=vm["id"]):
                self.assertEqual(pki.host_pki(inv, vm)["root_file"], "secrets/home/openbao-pki-root.crt")


if __name__ == "__main__":
    unittest.main()
