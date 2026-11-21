"""Tests for the security: block of network files and the network_security
filter (docs/plans/NETWORK-SECURITY.md, phase 1).

    .venv/bin/python -m unittest discover -s tests
"""

import copy
import importlib.util
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "network_config", ROOT / "plugins" / "filter" / "network_config.py")
nc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nc)

TEMPLATE_VM_ID = 110
TEMPLATE_IP = "192.168.1.10"
REPO_FILES = [{"file": p.stem, "config": yaml.safe_load(p.read_text())}
              for p in sorted((ROOT / "networks").glob("*.yaml"))]


def repo():
    """The repository's network files with every security: block removed,
    so tests don't depend on what home or lab declare today."""
    files = copy.deepcopy(REPO_FILES)
    for f in files:
        f["config"]["network"].pop("security", None)
    return files


def config(files, name):
    return next(f["config"] for f in files if f["file"] == name)


def add_home_openbao(files, **settings):
    """The home network with an openbao host that signs SSH user
    certificates, as in section 2.1 of the plan."""
    settings = {"tls": "self-signed", "ssh_user_ca": True, **settings}
    hosts = config(files, "home")["hosts"]
    bao = next((h for h in hosts if h["name"] == "openbao"), None)
    if bao is None:
        bao = {"name": "openbao", "type": "openbao", "vm_id": 120, "ip": "192.168.1.20",
               "data_disk": {"size_gb": 10, "storage": "local-lvm"}}
        hosts.append(bao)
    bao["settings"] = settings
    return files


def set_security(files, network, block):
    config(files, network)["network"]["security"] = block
    return files


def errors(files):
    return nc.network_config_errors(files, TEMPLATE_VM_ID, TEMPLATE_IP)


def warnings(files):
    return nc.network_config_warnings(files, TEMPLATE_VM_ID, TEMPLATE_IP)


def inventory(files):
    return nc.network_config_inventory({f["file"]: f["config"] for f in files})


def centralized(files):
    """home: centralized with secrets in files. agent-developer:
    centralized-local, trusting home.openbao."""
    add_home_openbao(files)
    set_security(files, "home", {"strategy": "centralized",
                                 "administrative_identity": {"instance": "home.openbao"},
                                 "secrets": {"provider": "files"}})
    set_security(files, "agent-developer", {"strategy": "centralized-local",
                                            "administrative_identity": {"instance": "home.openbao"}})
    return files


class NoSecurityBlock(unittest.TestCase):
    """A network without security: behaves exactly as before it existed."""

    def test_repo_networks_resolve_to_current(self):
        inv = inventory(repo())
        for f in REPO_FILES:
            name = f["file"]
            if "security" in f["config"]["network"]:
                continue
            has_openbao = any(h["type"] == "openbao" for h in f["config"].get("hosts") or [])
            with self.subTest(network=name):
                self.assertEqual(nc.network_security(inv, name), {
                    "strategy": "current",
                    "administrative_identity": {"provider": "keys", "instance": "", "ssh_host_ca": False,
                                                "principals": {}},
                    "secrets": ({"provider": "openbao", "instance": f"{name}.openbao"} if has_openbao
                                else {"provider": "files", "instance": ""}),
                    "pki": {"provider": "proxy-internal", "instance": ""},
                })

    def test_repo_files_are_valid(self):
        self.assertEqual(errors(copy.deepcopy(REPO_FILES)), [])

    def test_home_keeps_secrets_in_files(self):
        """home has an openbao host, but declares secrets: files
        (decision 10), so nats keeps reading secrets/home/nats.env."""
        self.assertEqual(nc.network_secrets_store(inventory(copy.deepcopy(REPO_FILES)), "home"), {})

    def test_secrets_store_is_unchanged(self):
        """network_secrets_store gives what it gave before: the network's
        openbao host when it has one, {} otherwise."""
        inv = inventory(repo())
        for f in REPO_FILES:
            name = f["file"]
            if "security" in f["config"]["network"]:
                continue
            bao = next((h for h in f["config"].get("hosts") or [] if h["type"] == "openbao"), None)
            store = nc.network_secrets_store(inv, name)
            with self.subTest(network=name):
                if bao is None:
                    self.assertEqual(store, {})
                else:
                    self.assertEqual(store, {
                        "host_id": f"{name}.{bao['name']}", "name": bao["name"], "mount": name,
                        "url": f"http://{bao['ip']}:8200",
                        "via_router": inv["hosts"][f"{name}.{bao['name']}"]["attach"]["via_router"],
                        "init_file": f"secrets/{name}/{bao['name']}-init.json"})

    def test_no_security_warnings(self):
        self.assertFalse([w for w in warnings(repo()) if "security" in w or "not deployed yet" in w])


class Presets(unittest.TestCase):
    def test_centralized_example_is_valid(self):
        self.assertEqual(errors(centralized(repo())), [])

    def test_centralized_example_resolves(self):
        inv = inventory(centralized(repo()))
        home = nc.network_security(inv, "home")
        dev = nc.network_security(inv, "agent-developer")
        self.assertEqual(home["administrative_identity"]["provider"], "openbao")
        self.assertEqual(home["administrative_identity"]["instance"], "home.openbao")
        self.assertEqual(home["secrets"], {"provider": "files", "instance": ""})
        self.assertEqual(dev["administrative_identity"]["instance"], "home.openbao")
        self.assertEqual(dev["secrets"], {"provider": "openbao", "instance": "agent-developer.openbao"})
        self.assertEqual(dev["pki"], {"provider": "proxy-internal", "instance": ""})
        self.assertEqual(dev["administrative_identity"]["principals"], {
            "admin": ["homelab-admin", "agent-developer-admin"],
            "operator": ["agent-developer-operator"]})

    def test_secrets_files_turns_off_the_store(self):
        """home has an openbao host, but keeps its secrets in files."""
        inv = inventory(centralized(repo()))
        self.assertEqual(nc.network_secrets_store(inv, "home"), {})
        self.assertEqual(nc.network_secrets_store(inv, "agent-developer")["host_id"], "agent-developer.openbao")

    def test_centralized_keeps_current_secrets_rule(self):
        files = add_home_openbao(repo())
        set_security(files, "agent-developer", {"strategy": "centralized",
                                                "administrative_identity": {"instance": "home.openbao"}})
        self.assertEqual(errors(files), [])
        sec = nc.network_security(inventory(files), "agent-developer")
        self.assertEqual(sec["secrets"]["instance"], "agent-developer.openbao")

    def test_independent_uses_own_openbao(self):
        files = repo()
        bao = next(h for h in config(files, "agent-developer")["hosts"] if h["type"] == "openbao")
        bao["settings"] = {"tls": "self-signed", "ssh_user_ca": True}
        set_security(files, "agent-developer", {"strategy": "independent"})
        self.assertEqual(errors(files), [])
        sec = nc.network_security(inventory(files), "agent-developer")
        self.assertEqual(sec["administrative_identity"]["instance"], "agent-developer.openbao")
        self.assertEqual(sec["secrets"]["instance"], "agent-developer.openbao")

    def test_principals_override(self):
        files = centralized(repo())
        config(files, "agent-developer")["network"]["security"]["administrative_identity"]["principals"] = {
            "admin": ["agent-developer-admin"]}
        self.assertEqual(errors(files), [])
        sec = nc.network_security(inventory(files), "agent-developer")
        self.assertEqual(sec["administrative_identity"]["principals"], {
            "admin": ["agent-developer-admin"], "operator": ["agent-developer-operator"]})

    def test_pki_from_own_openbao(self):
        files = centralized(repo())
        bao = next(h for h in config(files, "agent-developer")["hosts"] if h["type"] == "openbao")
        bao["settings"] = {"pki": True}
        config(files, "agent-developer")["network"]["security"]["pki"] = {"provider": "openbao"}
        self.assertEqual(errors(files), [])
        sec = nc.network_security(inventory(files), "agent-developer")
        self.assertEqual(sec["pki"], {"provider": "openbao", "instance": "agent-developer.openbao"})

    def test_not_deployed_settings_warn(self):
        files = centralized(repo())
        self.assertFalse([w for w in warnings(files) if "not deployed yet" in w])
        config(files, "agent-developer")["network"]["security"]["pki"] = {"provider": "openbao"}
        bao = next(h for h in config(files, "agent-developer")["hosts"] if h["type"] == "openbao")
        bao["settings"] = {"pki": True}
        found = warnings(files)
        self.assertTrue(any("pki is checked but not deployed yet" in w for w in found))
        self.assertTrue(any("settings.pki is checked but not deployed yet" in w for w in found))


class Rejected(unittest.TestCase):
    """Each rule of section 2.4 of the plan."""

    def assertError(self, files, text):
        found = errors(files)
        self.assertTrue(any(text in e for e in found), f"no error containing {text!r} in {found}")

    def with_dev(self, block):
        return set_security(add_home_openbao(repo()), "agent-developer", block)

    # 1. Unknown keys, strategies and providers.

    def test_unknown_key(self):
        self.assertError(self.with_dev({"stratgy": "current"}), "unknown setting stratgy")

    def test_unknown_block_key(self):
        self.assertError(self.with_dev({"secrets": {"provider": "files", "path": "x"}}),
                         "secrets: unknown setting path")

    def test_unknown_strategy(self):
        self.assertError(self.with_dev({"strategy": "central"}), "strategy must be one of")

    def test_unknown_provider(self):
        self.assertError(self.with_dev({"secrets": {"provider": "vault"}}), "secrets.provider must be one of")

    def test_not_a_mapping(self):
        self.assertError(self.with_dev("centralized"), "security: must be a mapping")

    def test_bad_instance(self):
        self.assertError(self.with_dev({"strategy": "centralized", "administrative_identity": {"instance": "openbao"}}),
                         "must be a host as <network>.<host>")

    # 2. Instances that aren't openbao hosts.

    def test_missing_network(self):
        self.assertError(self.with_dev({"strategy": "centralized",
                                        "administrative_identity": {"instance": "nowhere.openbao"}}),
                         "there's no network nowhere")

    def test_missing_host(self):
        self.assertError(self.with_dev({"strategy": "centralized",
                                        "administrative_identity": {"instance": "home.bao"}}),
                         "network home has no host bao")

    def test_not_openbao(self):
        self.assertError(self.with_dev({"strategy": "centralized",
                                        "administrative_identity": {"instance": "home.nats"}}),
                         "is a nats host, not an openbao host")

    # 3. Secrets and certificates only on the network's own OpenBao.

    def test_secrets_on_another_network(self):
        files = add_home_openbao(repo())
        set_security(files, "lab", {"secrets": {"provider": "openbao", "instance": "home.openbao"}})
        self.assertError(files, "secrets.instance home.openbao is on network home")

    def test_pki_on_another_network(self):
        files = add_home_openbao(repo(), pki=True)
        set_security(files, "agent-developer", {"pki": {"provider": "openbao", "instance": "home.openbao"}})
        self.assertError(files, "pki.instance home.openbao is on network home")

    def test_secrets_openbao_without_a_host(self):
        files = set_security(repo(), "lab", {"secrets": {"provider": "openbao"}})
        self.assertError(files, "secrets.provider openbao needs an openbao host on network lab")

    # 4. One isolated network never depends on another.

    def test_identity_from_another_isolated_network(self):
        files = repo()
        bao = next(h for h in config(files, "agent-developer")["hosts"] if h["type"] == "openbao")
        bao["settings"] = {"tls": "self-signed", "ssh_user_ca": True}
        set_security(files, "lab", {"strategy": "centralized",
                                    "administrative_identity": {"instance": "agent-developer.openbao"}})
        self.assertError(files, "which isn't a home network")

    # 5. The instance must provide what is asked of it.

    def test_instance_without_ssh_user_ca(self):
        files = add_home_openbao(repo(), ssh_user_ca=False)
        set_security(files, "agent-developer", {"strategy": "centralized",
                                                "administrative_identity": {"instance": "home.openbao"}})
        self.assertError(files, "doesn't have settings.ssh_user_ca: true")

    def test_instance_without_ssh_host_ca(self):
        self.assertError(self.with_dev({"strategy": "centralized",
                                        "administrative_identity": {"instance": "home.openbao", "ssh_host_ca": True}}),
                         "needs home.openbao to have settings.ssh_host_ca: true")

    def test_pki_instance_without_pki(self):
        self.assertError(self.with_dev({"pki": {"provider": "openbao"}}),
                         "doesn't have settings.pki set")

    def test_centralized_without_instance(self):
        self.assertError(self.with_dev({"strategy": "centralized"}), "administrative_identity needs an instance")

    # 6. Strategies that need a local OpenBao.

    def test_centralized_local_without_openbao(self):
        files = add_home_openbao(repo())
        set_security(files, "lab", {"strategy": "centralized-local",
                                    "administrative_identity": {"instance": "home.openbao"}})
        self.assertError(files, "strategy centralized-local needs an openbao host on network lab")

    def test_independent_with_home_instance(self):
        self.assertError(self.with_dev({"strategy": "independent",
                                        "administrative_identity": {"instance": "home.openbao"}}),
                         "strategy independent uses the network's own SSH user CA")

    # 7. A signing instance needs TLS.

    def test_signing_without_tls(self):
        files = add_home_openbao(repo(), tls="none")
        self.assertError(files, "settings.ssh_user_ca needs settings.tls")

    def test_bad_tls(self):
        files = add_home_openbao(repo(), tls="yes")
        self.assertError(files, "settings.tls must be one of")

    # 8. Overrides that contradict their preset.

    def test_current_with_openbao_identity(self):
        self.assertError(self.with_dev({"administrative_identity": {"provider": "openbao",
                                                                    "instance": "home.openbao"}}),
                         "strategy current uses static SSH keys")

    def test_centralized_with_keys(self):
        self.assertError(self.with_dev({"strategy": "centralized",
                                        "administrative_identity": {"provider": "keys"}}),
                         "administrative_identity.provider keys contradicts it")

    def test_centralized_local_with_files(self):
        self.assertError(self.with_dev({"strategy": "centralized-local",
                                        "administrative_identity": {"instance": "home.openbao"},
                                        "secrets": {"provider": "files"}}),
                         "secrets.provider files contradicts it")

    # Other shapes.

    def test_instance_with_keys(self):
        self.assertError(self.with_dev({"administrative_identity": {"instance": "home.openbao"}}),
                         "only apply with provider openbao")

    def test_secrets_instance_with_files(self):
        self.assertError(self.with_dev({"secrets": {"provider": "files", "instance": "agent-developer.openbao"}}),
                         "secrets.instance only applies with secrets.provider openbao")

    def test_principals_unknown_user(self):
        self.assertError(self.with_dev({"strategy": "centralized",
                                        "administrative_identity": {"instance": "home.openbao",
                                                                    "principals": {"root": ["x"]}}}),
                         "'root' isn't one of admin, operator")

    def test_principals_bad_names(self):
        self.assertError(self.with_dev({"strategy": "centralized",
                                        "administrative_identity": {"instance": "home.openbao",
                                                                    "principals": {"admin": ["Bad Name"]}}}),
                         "principals.admin must be a list of names")


class OpenbaoAuthority(unittest.TestCase):
    """What an openbao host provides (phase 2)."""

    def assertError(self, files, text):
        found = errors(files)
        self.assertTrue(any(text in e for e in found), f"no error containing {text!r} in {found}")

    def test_admins_valid(self):
        files = add_home_openbao(repo(), admins=[{"name": "alice", "roles": ["homelab-admin"]},
                                                 {"name": "alice-mfa", "roles": ["homelab-admin"], "mfa": True}],
                                 admin_mfa=False, admin_sources=["192.168.1.0/24", "192.168.1.5"],
                                 ssh_cert_max_ttl="24h")
        self.assertEqual(errors(files), [])

    def test_admin_bad_name(self):
        self.assertError(add_home_openbao(repo(), admins=[{"name": "Alice", "roles": ["homelab-admin"]}]),
                         "name 'Alice' must be lowercase")

    def test_admin_twice(self):
        a = {"name": "alice", "roles": ["homelab-admin"]}
        self.assertError(add_home_openbao(repo(), admins=[a, dict(a)]), "is listed twice")

    def test_admin_without_roles(self):
        self.assertError(add_home_openbao(repo(), admins=[{"name": "alice"}]), "roles must be a list")

    def test_admin_unknown_key(self):
        self.assertError(add_home_openbao(repo(), admins=[{"name": "alice", "roles": ["x"], "password": "p"}]),
                         "unknown setting password")

    def test_admin_mfa_not_bool(self):
        self.assertError(add_home_openbao(repo(), admins=[{"name": "alice", "roles": ["x"], "mfa": "yes"}]),
                         "mfa must be true or false")

    def test_admins_need_ssh_user_ca(self):
        self.assertError(add_home_openbao(repo(), ssh_user_ca=False, admins=[{"name": "a", "roles": ["x"]}]),
                         "settings.admins needs settings.ssh_user_ca: true")

    def test_bad_admin_sources(self):
        self.assertError(add_home_openbao(repo(), admin_sources=["desktop"]), "admin_sources must be a list")

    def test_bad_ttl(self):
        self.assertError(add_home_openbao(repo(), ssh_cert_max_ttl="1 day"), "ssh_cert_max_ttl must be a duration")

    def test_tls_pki_not_yet(self):
        self.assertError(add_home_openbao(repo(), tls="pki"), "settings.tls: pki isn't available yet")


class Filters(unittest.TestCase):
    def test_ssh_roles(self):
        files = centralized(repo())
        set_security(files, "lab", {"strategy": "centralized",
                                    "administrative_identity": {"instance": "home.openbao"}})
        self.assertEqual(nc.openbao_ssh_roles(inventory(files), "home.openbao"), [
            "homelab-admin", "agent-developer-admin", "agent-developer-operator",
            "home-admin", "home-operator", "lab-admin", "lab-operator"])

    def test_ssh_roles_follow_principals(self):
        files = centralized(repo())
        config(files, "agent-developer")["network"]["security"]["administrative_identity"]["principals"] = {
            "admin": ["dev-root"], "operator": []}
        roles = nc.openbao_ssh_roles(inventory(files), "home.openbao")
        self.assertIn("dev-root", roles)
        self.assertNotIn("agent-developer-admin", roles)

    def test_ssh_admin_roles(self):
        self.assertEqual(nc.openbao_ssh_admin_roles(inventory(centralized(repo())), "home.openbao"),
                         ["agent-developer-admin", "home-admin", "homelab-admin"])

    def test_ssh_roles_without_users(self):
        self.assertEqual(nc.openbao_ssh_roles(inventory(repo()), "home.openbao"), ["homelab-admin"])

    def test_trust_principals(self):
        sec = nc.network_security(inventory(centralized(repo())), "agent-developer")
        self.assertEqual(nc.ssh_trust_principals(sec, "dev"), {
            "admin": ["homelab-admin", "agent-developer-admin"], "dev": ["agent-developer-operator"]})
        self.assertEqual(nc.ssh_trust_principals(sec), {"admin": ["homelab-admin", "agent-developer-admin"]})

    def test_trust_principals_keys(self):
        sec = nc.network_security(inventory(repo()), "lab")
        self.assertEqual(nc.ssh_trust_principals(sec, "dev"), {})


if __name__ == "__main__":
    unittest.main()
