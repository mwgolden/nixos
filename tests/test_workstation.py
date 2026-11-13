"""Tests for plugins/filter/workstation.py: settings.tools,
settings.environment, and what the deploy installs, upgrades or removes.

    .venv/bin/python -m unittest discover -s tests
"""

import importlib.util
import json
import pathlib
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location(
    "workstation", ROOT / "plugins" / "filter" / "workstation.py")
ws = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ws)

HOME = "/home/dev"


def installed(npm=None, uv=None, curl=None, available=("npm", "uv")):
    return {"npm": npm or {}, "uv": uv or {}, "curl": curl or {},
            "available": {k: k in available for k in ("npm", "uv")}}


def plan(tools, record=None, inst=None, upgrade=False):
    return [(a["action"], a["entry"]["name"])
            for a in ws.workstation_tool_actions(tools, record or [], inst or installed(), upgrade, HOME)]


class ToolChecks(unittest.TestCase):
    def assertValid(self, tools):
        self.assertEqual(ws.workstation_tools_errors(tools), [])

    def assertInvalid(self, tools, text):
        errors = ws.workstation_tools_errors(tools)
        self.assertTrue(any(text in e for e in errors), errors)

    def test_valid_tools(self):
        self.assertValid([
            {"npm": "@anthropic-ai/claude-code"},
            {"npm": "typescript", "version": "5.6.3"},
            {"npm": "pkg", "version": "1.0.0-beta.2"},
            {"uv": "ruff", "version": "0.8.4"},
            {"uv": "llm", "with": ["llm-anthropic==0.12", "llm-gpt4all"], "python": "3.12"},
            {"uv": "httpie[socks]"},
            {"uv": "black", "version": "24.1.0rc1"},
            {"curl": "https://example.com/install.sh", "creates": "~/.local/bin/example"},
        ])

    def test_not_a_list(self):
        self.assertInvalid({"uv": "ruff"}, "must be a list")

    def test_one_kind_per_entry(self):
        self.assertInvalid([{"uv": "ruff", "npm": "ruff"}], "exactly one of")
        self.assertInvalid([{"pip": "ruff"}], "exactly one of")

    def test_injection_in_names(self):
        self.assertInvalid([{"npm": "x; rm -rf ~"}], "npm package name")
        self.assertInvalid([{"uv": "ruff && curl evil"}], "PyPI package name")
        self.assertInvalid([{"uv": "llm", "with": ["a b"]}], "with entry")
        self.assertInvalid([{"uv": "llm", "with": ["--index-url=http://x"]}], "with entry")

    def test_version_goes_in_version(self):
        self.assertInvalid([{"uv": "ruff==0.8"}], "PyPI package name")
        self.assertInvalid([{"npm": "typescript@5.6.3"}], "npm package name")

    def test_ranges_not_allowed(self):
        self.assertInvalid([{"npm": "typescript", "version": "^5.6"}], "one exact version")
        self.assertInvalid([{"uv": "ruff", "version": ">=0.8,<0.9"}], "one exact version")
        self.assertInvalid([{"npm": "typescript", "version": "5.6"}], "one exact version")

    def test_unquoted_version(self):
        self.assertInvalid([{"uv": "ruff", "version": 0.1}], "quoted text")

    def test_version_only_on_npm_and_uv(self):
        self.assertInvalid([{"curl": "https://x.dev/i.sh", "creates": "~/.local/bin/x",
                             "version": "1.0.0"}], "unknown setting version")
        self.assertInvalid([{"npm": "typescript", "with": ["x"]}], "unknown setting with")

    def test_curl(self):
        self.assertInvalid([{"curl": "http://example.com/i.sh", "creates": "~/x"}], "https://")
        self.assertInvalid([{"curl": "https://example.com/i.sh"}], "needs creates")
        self.assertInvalid([{"curl": "https://example.com/i.sh", "creates": "/usr/bin/x"}], "needs creates")
        self.assertInvalid([{"curl": "https://example.com/i.sh", "creates": "~/../root/x"}], "needs creates")

    def test_python(self):
        self.assertInvalid([{"uv": "llm", "python": 3.12}], "python must be")
        self.assertInvalid([{"uv": "llm", "python": "2.7"}], "python must be")

    def test_duplicates(self):
        self.assertInvalid([{"uv": "ruff"}, {"uv": "Ruff"}], "listed twice")
        self.assertInvalid([{"uv": "my_tool"}, {"uv": "my-tool"}], "listed twice")
        self.assertValid([{"uv": "ruff"}, {"npm": "ruff"}])


class EnvironmentChecks(unittest.TestCase):
    def errors(self, env, secrets=None, names=None):
        secrets = secrets or {}
        names = names if names is not None else ["WORKSTATION_ENV_" + n for n in secrets]
        return ws.workstation_env_errors(env, secrets, names)

    def test_valid(self):
        self.assertEqual(self.errors({"EDITOR": "vim", "DEBUG": 1, "ON": True},
                                     {"ANTHROPIC_API_KEY": "sk"}), [])

    def test_secret_prefix_removed(self):
        self.assertEqual(ws.workstation_secret_env(
            {"WORKSTATION_PASSWORD_HASH": "$6$x", "WORKSTATION_ENV_TOKEN": "t"}), {"TOKEN": "t"})

    def test_bad_names(self):
        self.assertTrue(self.errors({"MY-KEY": "x"}))
        self.assertTrue(self.errors({"1X": "x"}))
        self.assertTrue(self.errors({}, names=["WORKSTATION_ENV_MY-KEY"]))

    def test_reserved(self):
        for name in ("PATH", "HOME", "SHELL", "npm_config_prefix", "LD_PRELOAD", "NIX_PATH"):
            self.assertTrue(self.errors({name: "x"}), name)
        self.assertTrue(self.errors({}, {"PATH": "x"}))

    def test_not_a_single_value(self):
        self.assertTrue(self.errors({"X": None}))
        self.assertTrue(self.errors({"X": ["a"]}))

    def test_clash(self):
        errors = self.errors({"TOKEN": "a"}, {"TOKEN": "b"})
        self.assertTrue(any("both" in e for e in errors), errors)

    def test_errors_never_show_values(self):
        errors = self.errors({"PATH": "secret-value"}, {"HOME": "other-secret"})
        self.assertFalse(any("secret" in e and "value" in e for e in errors))
        self.assertFalse(any("other-secret" in e for e in errors))


class EnvFile(unittest.TestCase):
    def source(self, text):
        """The variables bash sees after sourcing the file the way
        configuration.nix does."""
        script = 'set -a; . /dev/stdin; set +a; env -0'
        out = subprocess.run(["bash", "-c", script], input=text, capture_output=True,
                             text=True, env={"HOME": HOME, "PATH": "/usr/bin:/bin"}, check=True).stdout
        return dict(item.split("=", 1) for item in out.split("\0") if "=" in item)

    def test_values_survive_quoting(self):
        tricky = {"A": "two words", "B": "it's", "C": "$HOME `id` $(id)", "D": 'a"b', "E": "line1\nline2",
                  "F": True, "G": 3, "H": ""}
        env = self.source(ws.workstation_env_file(tricky, {"KEY": "sk-ant-$x'y"}))
        self.assertEqual(env["A"], "two words")
        self.assertEqual(env["B"], "it's")
        self.assertEqual(env["C"], "$HOME `id` $(id)")
        self.assertEqual(env["D"], 'a"b')
        self.assertEqual(env["E"], "line1\nline2")
        self.assertEqual(env["F"], "true")
        self.assertEqual(env["G"], "3")
        self.assertEqual(env["H"], "")
        self.assertEqual(env["KEY"], "sk-ant-$x'y")

    def test_defaults(self):
        env = self.source(ws.workstation_env_file({}, {}))
        self.assertEqual(env["PATH"], f"{HOME}/.local/bin:{HOME}/.npm-global/bin:/usr/bin:/bin")
        self.assertEqual(env["NPM_CONFIG_PREFIX"], f"{HOME}/.npm-global")
        self.assertEqual(env["UV_PYTHON_PREFERENCE"], "only-managed")

    def test_settings_override_defaults(self):
        env = self.source(ws.workstation_env_file({"UV_PYTHON_PREFERENCE": "system"}, {}))
        self.assertEqual(env["UV_PYTHON_PREFERENCE"], "system")


class PackageManagers(unittest.TestCase):
    def errors(self, tools, packages):
        return ws.workstation_package_manager_errors(tools, packages)

    def test_required_in_packages(self):
        errors = self.errors([{"npm": "x"}, {"uv": "y"}], [])
        self.assertEqual(len(errors), 2)
        self.assertIn("'- nodejs_22'", errors[0])
        self.assertIn("'- uv'", errors[1])

    def test_accepted_packages(self):
        for package in ("uv", "python3Packages.uv", "python313Packages.uv"):
            self.assertEqual(self.errors([{"uv": "y"}], [package]), [], package)
        for package in ("nodejs", "nodejs_20", "nodejs_22"):
            self.assertEqual(self.errors([{"npm": "x"}], [package]), [], package)

    def test_rejected_packages(self):
        self.assertTrue(self.errors([{"npm": "x"}], ["nodejs-slim_22"]))
        self.assertTrue(self.errors([{"uv": "y"}], ["uvicorn"]))
        self.assertTrue(self.errors([{"uv": "y"}], ["python3Packages.uvloop"]))

    def test_not_needed(self):
        self.assertEqual(self.errors([{"curl": "https://x", "creates": "~/x"}], []), [])
        self.assertEqual(self.errors([], []), [])
        self.assertEqual(self.errors([], ["uv"]), [])


class Installed(unittest.TestCase):
    def test_npm_ls(self):
        out = json.dumps({"dependencies": {"typescript": {"version": "5.6.3"},
                                           "@anthropic-ai/claude-code": {"version": "2.0.1"}}})
        self.assertEqual(ws.workstation_npm_installed(out),
                         {"typescript": "5.6.3", "@anthropic-ai/claude-code": "2.0.1"})
        self.assertEqual(ws.workstation_npm_installed("{}"), {})
        self.assertEqual(ws.workstation_npm_installed(""), {})

    def test_uv_tool_list(self):
        out = "ruff v0.8.4\n- ruff\nMy_Tool v1.2.0rc1\n- my-tool\n"
        self.assertEqual(ws.workstation_uv_installed(out), {"ruff": "0.8.4", "my-tool": "1.2.0rc1"})
        self.assertEqual(ws.workstation_uv_installed("No tools installed"), {})


class Actions(unittest.TestCase):
    """The rows of the Versions table in docs/plans/completed/WORKSTATION-TOOLS.md."""

    def test_missing_tools_are_installed(self):
        self.assertEqual(plan([{"npm": "typescript"}, {"uv": "ruff", "version": "0.8.4"}]),
                         [("install", "typescript"), ("install", "ruff")])

    def test_unpinned_left_alone(self):
        self.assertEqual(plan([{"npm": "typescript"}, {"uv": "ruff"}],
                              inst=installed(npm={"typescript": "5.0.0"}, uv={"ruff": "0.1.0"})),
                         [("keep", "typescript"), ("keep", "ruff")])

    def test_unpinned_upgraded_with_flag(self):
        actions = ws.workstation_tool_actions(
            [{"npm": "typescript"}, {"uv": "ruff"}], [],
            installed(npm={"typescript": "5.0.0"}, uv={"ruff": "0.1.0"}), True, HOME)
        self.assertEqual([(a["action"], a["argv"]) for a in actions], [
            ("upgrade", ["npm", "install", "--global", "--no-fund", "--no-audit", "typescript@latest"]),
            ("upgrade", ["uv", "tool", "upgrade", "ruff"])])

    def test_pins_enforced(self):
        actions = ws.workstation_tool_actions(
            [{"npm": "typescript", "version": "5.6.3"}, {"uv": "ruff", "version": "0.8.4"}], [],
            installed(npm={"typescript": "5.7.0"}, uv={"ruff": "0.9.0"}), False, HOME)
        self.assertEqual([(a["action"], a["argv"]) for a in actions], [
            ("install", ["npm", "install", "--global", "--no-fund", "--no-audit", "typescript@5.6.3"]),
            ("reinstall", ["uv", "tool", "install", "--reinstall", "ruff==0.8.4"])])

    def test_pinned_not_upgraded(self):
        self.assertEqual(plan([{"uv": "ruff", "version": "0.8.4"}],
                              inst=installed(uv={"ruff": "0.8.4"}), upgrade=True),
                         [("keep", "ruff")])

    def test_changed_with_reinstalls(self):
        tools = [{"uv": "llm", "with": ["llm-anthropic==0.12"]}]
        record = [{"kind": "uv", "name": "llm", "version": None, "with": ["llm-anthropic"], "python": None}]
        actions = ws.workstation_tool_actions(tools, record, installed(uv={"llm": "0.19"}), False, HOME)
        self.assertEqual(actions[0]["action"], "reinstall")
        self.assertEqual(actions[0]["argv"],
                         ["uv", "tool", "install", "--reinstall", "--with", "llm-anthropic==0.12", "llm"])

    def test_unchanged_with_kept(self):
        tools = [{"uv": "llm", "with": ["llm-anthropic"], "python": "3.12"}]
        record = ws.workstation_tool_record(tools)
        self.assertEqual(plan(tools, record, installed(uv={"llm": "0.19"})), [("keep", "llm")])

    def test_hand_installed_tool_with_extras_reinstalled_once_listed(self):
        self.assertEqual(plan([{"uv": "llm", "with": ["llm-anthropic"]}],
                              inst=installed(uv={"llm": "0.19"})), [("reinstall", "llm")])

    def test_removed_tools_uninstalled_only_if_recorded(self):
        record = [{"kind": "uv", "name": "ruff", "version": None, "with": [], "python": None},
                  {"kind": "npm", "name": "typescript", "version": None}]
        inst = installed(npm={"typescript": "5.0.0", "prettier": "3.0.0"},
                         uv={"ruff": "0.1.0", "black": "24.1.0"})
        actions = ws.workstation_tool_actions([], record, inst, False, HOME)
        self.assertEqual([(a["action"], a["argv"]) for a in actions], [
            ("uninstall", ["uv", "tool", "uninstall", "ruff"]),
            ("uninstall", ["npm", "uninstall", "--global", "typescript"])])

    def test_removed_tool_already_gone(self):
        record = [{"kind": "uv", "name": "ruff", "version": None, "with": [], "python": None}]
        self.assertEqual(plan([], record), [])

    def test_removed_without_package_manager(self):
        record = [{"kind": "npm", "name": "typescript", "version": None}]
        self.assertEqual(plan([], record, installed(available=())), [("leave", "typescript")])

    def test_curl(self):
        tool = {"curl": "https://example.com/install.sh", "creates": "~/.local/bin/example"}
        actions = ws.workstation_tool_actions([tool], [], installed(), False, HOME)
        self.assertEqual(actions[0]["action"], "install")
        self.assertEqual(actions[0]["creates"], "/home/dev/.local/bin/example")
        self.assertTrue(actions[0]["script"].startswith("/home/dev/.cache/nixlab/"))
        self.assertEqual(actions[0]["argv"], ["bash", actions[0]["script"]])
        present = installed(curl={tool["curl"]: True})
        self.assertEqual(plan([tool], inst=present), [("keep", tool["curl"])])
        self.assertEqual(plan([tool], inst=present, upgrade=True), [("install", tool["curl"])])
        record = ws.workstation_tool_record([tool])
        self.assertEqual(plan([], record, present), [("leave", tool["curl"])])

    def test_pypi_names_compared_normalized(self):
        self.assertEqual(plan([{"uv": "My_Tool"}], inst=installed(uv={"my-tool": "1.0"})),
                         [("keep", "My_Tool")])

    def test_python_and_extras(self):
        actions = ws.workstation_tool_actions([{"uv": "httpie[socks]", "python": "3.12", "version": "3.2.4"}],
                                              [], installed(), False, HOME)
        self.assertEqual(actions[0]["argv"],
                         ["uv", "tool", "install", "--python", "3.12", "httpie[socks]==3.2.4"])


class AfterInstall(unittest.TestCase):
    def test_pin_errors(self):
        tools = [{"npm": "typescript", "version": "5.6.3"}, {"uv": "ruff"}]
        self.assertEqual(ws.workstation_pin_errors(tools, installed(npm={"typescript": "5.6.3"})), [])
        self.assertEqual(len(ws.workstation_pin_errors(tools, installed(npm={"typescript": "5.7.0"}))), 1)

    def test_versions(self):
        tools = [{"npm": "typescript", "version": "5.6.3"}, {"uv": "ruff"}]
        self.assertEqual(ws.workstation_tool_versions(tools, installed(npm={"typescript": "5.6.3"})),
                         ["npm: typescript 5.6.3 (pinned)", "uv: ruff not installed"])


if __name__ == "__main__":
    unittest.main()
