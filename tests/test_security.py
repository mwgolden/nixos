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


def without_openbao(files, network):
    hosts = config(files, network)["hosts"]
    hosts[:] = [h for h in hosts if h["type"] != "openbao"]
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
                        "init_file": f"secrets/{name}/{bao['name']}-init.json",
                        "deploy_token_file": f"secrets/{name}/{bao['name']}-deploy-token",
                        "ca_file": ""})

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

    def test_pki_openbao_is_deferred(self):
        files = centralized(repo())
        config(files, "agent-developer")["network"]["security"]["pki"] = {"provider": "openbao"}
        found = errors(files)
        self.assertTrue(any("pki.provider openbao isn't available" in e for e in found), found)
    def test_no_not_deployed_warnings(self):
        self.assertFalse([w for w in warnings(centralized(repo())) if "not deployed yet" in w])

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

    def test_openbao_pki_setting_is_deferred(self):
        self.assertError(add_home_openbao(repo(), pki=True), "settings.pki isn't available")
    def test_secrets_openbao_without_a_host(self):
        files = set_security(without_openbao(repo(), "lab"), "lab", {"secrets": {"provider": "openbao"}})
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

    def test_pki_proxy_internal_is_fine(self):
        self.assertEqual(errors(self.with_dev({"pki": {"provider": "proxy-internal"}})), [])
    def test_centralized_without_instance(self):
        self.assertError(self.with_dev({"strategy": "centralized"}), "administrative_identity needs an instance")

    # 6. Strategies that need a local OpenBao.

    def test_centralized_local_without_openbao(self):
        files = without_openbao(add_home_openbao(repo()), "lab")
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
        self.assertError(add_home_openbao(repo(), tls="pki"), "settings.tls: pki isn't available")


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


class HostCA(unittest.TestCase):
    def files(self):
        files = add_home_openbao(repo(), ssh_host_ca=True)
        set_security(files, "home", {"strategy": "centralized", "secrets": {"provider": "files"},
                                     "administrative_identity": {"instance": "home.openbao", "ssh_host_ca": True}})
        set_security(files, "lab", {"strategy": "centralized",
                                    "administrative_identity": {"instance": "home.openbao", "ssh_host_ca": True}})
        return files

    def test_valid_without_warnings(self):
        files = self.files()
        self.assertEqual(errors(files), [])
        self.assertFalse([w for w in warnings(files) if "ssh_host_ca" in w])

    def test_host_principals(self):
        inv = inventory(self.files())
        self.assertEqual(nc.ssh_host_principals(inv["hosts"]["home.nats"]),
                         ["nats", "nats.home.home.arpa", "192.168.1.18"])
        self.assertEqual(nc.ssh_host_principals(inv["hosts"]["lab.router"]),
                         ["router", "router.lab.home.arpa", "10.1.0.1", "192.168.1.13"])

    def test_host_roles(self):
        roles = nc.openbao_ssh_host_roles(inventory(self.files()), "home.openbao")
        self.assertEqual([r["name"] for r in roles], ["hosts-home", "hosts-lab"])
        lab = roles[1]["principals"]
        self.assertIn("192.168.1.13", lab)
        self.assertNotIn("192.168.1.18", lab)

    def test_no_host_roles_without_ssh_host_ca(self):
        self.assertEqual(nc.openbao_ssh_host_roles(inventory(centralized(repo())), "home.openbao"), [])

    def test_endpoint(self):
        inv = inventory(self.files())
        self.assertEqual(nc.openbao_endpoint(inv, "home.openbao"), {
            "url": "https://192.168.1.20:8200", "ca_file": "secrets/home/openbao-tls.crt",
            "init_file": "secrets/home/openbao-init.json", "via_router": ""})

    def test_bad_host_ttl(self):
        found = errors(add_home_openbao(repo(), ssh_host_cert_ttl="a year"))
        self.assertTrue(any("ssh_host_cert_ttl must be a duration" in e for e in found))


class ReadTokens(unittest.TestCase):
    def test_one_per_host_with_exact_paths(self):
        tokens = nc.openbao_read_tokens(inventory(repo()), "agent-developer")
        by_host = {t["host"]: t for t in tokens}
        self.assertNotIn("router", by_host)
        self.assertNotIn("openbao", by_host)
        self.assertEqual(by_host["postgres"]["paths"], ["postgres", "postgres-users"])
        self.assertEqual(by_host["gitea"]["paths"], ["gitea"])
        self.assertEqual(by_host["gitea"]["name"], "agent-developer-gitea-read")
        self.assertEqual(by_host["gitea"]["file"], "secrets/agent-developer/gitea-read-token")

    def test_deploy_policy_has_real_lines(self):
        token = nc.openbao_deploy_token("lab", "openbao")
        self.assertEqual(token["file"], "secrets/lab/openbao-deploy-token")
        self.assertIn('\npath "lab/data/*" {\n  capabilities = ["create", "read", "update"]\n}', token["policy"])
        self.assertNotIn("\\n", token["policy"])

    def test_isolated_hosts_are_blocked_from_other_openbaos(self):
        inv = inventory(repo())
        targets = nc.blocked_targets(inv["hosts"]["agent-developer.gitea"], inv)
        self.assertIn({"name": "home.openbao's OpenBao", "host": "192.168.1.20", "port": 8200}, targets)
        self.assertFalse([t for t in targets if t["host"] == "10.3.1.5"])


if __name__ == "__main__":
    unittest.main()
