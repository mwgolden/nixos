"""Checks and decisions for a workstation's user tools and environment
variables (settings.tools and settings.environment). See
roles/workstation/README.md and docs/plans/WORKSTATION-TOOLS.md.

Used from roles/workstation:

    {{ workstation_tools | workstation_tools_errors }}
    {{ workstation_tools | workstation_tool_actions(record, installed, upgrade, home) }}

Tools are installed in the user's home, as the user, after the NixOS
switch: npm packages under ~/.npm-global, uv tools under ~/.local, and
install scripts fetched with curl wherever they put themselves.
"""

import hashlib
import json
import re
import shlex

KINDS = ("npm", "uv", "curl")
TOOL_KEYS = {
    "npm": {"npm", "version"},
    "uv": {"uv", "version", "with", "python"},
    "curl": {"curl", "creates"},
}

NPM_NAME_RE = re.compile(r"^(@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*$")
# A PyPI name with optional extras, such as llm or httpie[socks].
PYPI_NAME = r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"
PYPI_EXTRAS = r"(?:\[[A-Za-z0-9._-]+(?:,[A-Za-z0-9._-]+)*\])?"
UV_NAME_RE = re.compile(rf"^{PYPI_NAME}{PYPI_EXTRAS}$")
# A PEP 508 requirement without markers or URLs: name, extras, specifiers.
SPECIFIER = r"(?:==|!=|>=|<=|~=|>|<)[A-Za-z0-9.*+!_-]+"
UV_WITH_RE = re.compile(rf"^{PYPI_NAME}{PYPI_EXTRAS}(?:{SPECIFIER}(?:,{SPECIFIER})*)?$")
# One exact version: semver for npm, PEP 440 (without epochs or local
# versions) for PyPI.
NPM_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
UV_VERSION_RE = re.compile(r"^\d+(?:\.\d+)*(?:(?:a|b|rc)\d+)?(?:\.post\d+)?(?:\.dev\d+)?$")
PYTHON_RE = re.compile(r"^3\.\d+(?:\.\d+)?$")
URL_RE = re.compile(r"^https://[A-Za-z0-9.-]+(?::\d+)?(?:/[A-Za-z0-9._~%!$&()*+,;=:@/?-]*)?$")
CREATES_RE = re.compile(r"^~/[A-Za-z0-9._+-]+(?:/[A-Za-z0-9._+-]+)*$")

ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# Names the deploy sets itself, or that would break logins or Nix.
RESERVED_ENV = {"PATH", "HOME", "USER", "LOGNAME", "SHELL", "NPM_CONFIG_PREFIX"}
RESERVED_ENV_PREFIXES = ("LD_", "NIX_")
SECRET_ENV_PREFIX = "WORKSTATION_ENV_"

# Where things go in the user's home.
NPM_PREFIX = ".npm-global"
ENV_FILE = ".config/nixlab/env"
SCRIPT_DIR = ".cache/nixlab"
# Written first in the env file, as they are (values already in shell
# form). Later lines, from the host's settings, can override the ones that
# aren't reserved.
ENV_DEFAULTS = [
    ("PATH", '"$HOME/.local/bin:$HOME/.npm-global/bin:$PATH"'),
    ("NPM_CONFIG_PREFIX", '"$HOME/.npm-global"'),
    # uv's own Pythons, not the system one: a tool's environment then keeps
    # working after a NixOS upgrade replaces the system Python's store path.
    # They run through nix-ld.
    ("UV_PYTHON_PREFERENCE", "only-managed"),
]


def pypi_normalize(name):
    """A PyPI name as uv and pip compare it (PEP 503), without extras."""
    return re.sub(r"[-_.]+", "-", name.split("[", 1)[0]).lower()


def _version_text(value):
    return value if isinstance(value, str) else None


# Checks

def workstation_tools_errors(tools, where="settings.tools"):
    """Problems with settings.tools, as messages. Empty when valid."""
    if not isinstance(tools, list):
        return [f"{where} must be a list."]
    errors = []
    seen = {}
    for index, tool in enumerate(tools):
        at = f"{where}[{index}]"
        if not isinstance(tool, dict):
            errors.append(f"{at} must be a mapping such as {{uv: ruff}}, not {tool!r}.")
            continue
        kinds = [k for k in KINDS if k in tool]
        if len(kinds) != 1:
            errors.append(f"{at} must have exactly one of npm:, uv: or curl:.")
            continue
        kind = kinds[0]
        name = tool[kind]
        at = f"{at} ({kind}: {name})"
        for key in sorted(set(tool) - TOOL_KEYS[kind]):
            errors.append(f"{at}: unknown setting {key}. A {kind} tool takes "
                          f"{', '.join(sorted(TOOL_KEYS[kind] - {kind}))}.")
        if not isinstance(name, str):
            errors.append(f"{at}: {kind} must be a string.")
            continue

        if kind == "npm":
            if not NPM_NAME_RE.match(name):
                errors.append(f"{at}: not an npm package name like typescript or @scope/name. "
                              "Put a version under version:, not in the name.")
            key = ("npm", name)
        elif kind == "uv":
            if not UV_NAME_RE.match(name):
                errors.append(f"{at}: not a PyPI package name like ruff or httpie[socks]. "
                              "Put a version under version:, not in the name.")
            key = ("uv", pypi_normalize(name))
        else:
            if not URL_RE.match(name):
                errors.append(f"{at}: curl must be an https:// URL of an install script.")
            creates = tool.get("creates")
            if not isinstance(creates, str) or not CREATES_RE.match(creates) or "/../" in creates + "/":
                errors.append(f"{at}: needs creates:, a path in the user's home starting with ~/, "
                              "such as ~/.local/bin/tool. The deploy runs the script only when it's missing.")
            key = ("curl", name)

        if "version" in tool:
            version = _version_text(tool["version"])
            pattern = NPM_VERSION_RE if kind == "npm" else UV_VERSION_RE
            example = "5.6.3" if kind == "npm" else "0.8.4"
            if version is None:
                errors.append(f"{at}: version must be quoted text such as \"{example}\", "
                              f"not {tool['version']!r}. YAML reads 0.10 as the number 0.1.")
            elif not pattern.match(version):
                errors.append(f"{at}: version must be one exact version such as {example}, "
                              f"not '{version}'. Ranges aren't allowed, so the pin can be checked.")

        if kind == "uv":
            extra = tool.get("with", [])
            if not isinstance(extra, list) or not all(isinstance(w, str) for w in extra):
                errors.append(f"{at}: with must be a list of PyPI requirements.")
            else:
                for w in extra:
                    if not UV_WITH_RE.match(w):
                        errors.append(f"{at}: with entry '{w}' must be a PyPI requirement such as "
                                      "llm-anthropic or llm-anthropic==0.12, with no spaces.")
            if "python" in tool:
                python = tool["python"]
                if not isinstance(python, str) or not PYTHON_RE.match(python):
                    errors.append(f"{at}: python must be quoted text such as \"3.12\", not {python!r}.")

        if key in seen:
            errors.append(f"{at}: listed twice, also as {seen[key]}.")
        else:
            seen[key] = at
    return errors


def workstation_secret_env(values):
    """The WORKSTATION_ENV_* entries of a secrets file, prefix removed."""
    return {k[len(SECRET_ENV_PREFIX):]: v for k, v in (values or {}).items()
            if k.startswith(SECRET_ENV_PREFIX)}


def _env_name_error(name):
    if not ENV_NAME_RE.match(name):
        return "isn't a valid variable name: letters, digits and _, not starting with a digit"
    if name.upper() in RESERVED_ENV or name.upper().startswith(RESERVED_ENV_PREFIXES):
        return ("is set by the deploy or NixOS, so it can't be changed here "
                f"(reserved: {', '.join(sorted(RESERVED_ENV))}, LD_*, NIX_*)")
    return None


def workstation_env_errors(environment, secret_env, secret_names=(), where="settings.environment",
                           secrets_where="the secrets file"):
    """Problems with settings.environment and the secret variables, as
    messages. secret_names is every WORKSTATION_ENV_ name in the secrets
    file, including ones the .env reader skipped as invalid."""
    errors = []
    if not isinstance(environment, dict):
        return [f"{where} must be a mapping of NAME: value."]
    for name, value in environment.items():
        if not isinstance(name, str):
            errors.append(f"{where}: name {name!r} must be text.")
            continue
        problem = _env_name_error(name)
        if problem:
            errors.append(f"{where}: {name} {problem}.")
        if value is None or isinstance(value, (dict, list)):
            errors.append(f"{where}: {name} must have a single value, such as a word or quoted text.")
    for full in secret_names:
        name = full[len(SECRET_ENV_PREFIX):]
        problem = _env_name_error(name)
        if problem:
            errors.append(f"{secrets_where}: {full} sets {name}, which {problem}.")
    for name in secret_env:
        if name in environment:
            errors.append(f"{name} is set both in {where} and as {SECRET_ENV_PREFIX}{name} "
                          f"in {secrets_where}. Keep one.")
    return errors


# The env file

def _env_value(value):
    if isinstance(value, bool):
        value = "true" if value else "false"
    return shlex.quote(str(value))


def workstation_env_file(environment, secret_env):
    """The text of ~/.config/nixlab/env: defaults, then the host's
    environment, then its secret variables. Every value is shell-quoted."""
    lines = [
        "# Written by the deploy (roles/workstation). Changes here are lost on the next deploy:",
        "# set variables in the host's settings.environment, or as WORKSTATION_ENV_<NAME>",
        "# in its secrets file. Every shell loads this file (environment.extraInit).",
    ]
    for name, value in ENV_DEFAULTS:
        lines.append(f"{name}={value}")
    for name, value in environment.items():
        lines.append(f"{name}={_env_value(value)}")
    for name in sorted(secret_env):
        lines.append(f"{name}={_env_value(secret_env[name])}")
    return "\n".join(lines) + "\n"


# Package managers

# nixpkgs packages that provide each kind's package manager. nodejs-slim
# packages are left out: they don't include npm.
PACKAGE_MANAGERS = {
    "npm": (re.compile(r"^nodejs(_\d+)?$"), "nodejs_22", "Node.js, which includes npm,"),
    "uv": (re.compile(r"^(uv|python3\d*Packages\.uv)$"), "uv", "uv"),
}


def workstation_package_manager_errors(tools, packages, where="settings"):
    """npm and uv tools need their package manager in settings.packages.
    The deploy never adds it, so removing a tool never removes the package
    manager, and the user has it for their own use."""
    kinds = {k for t in tools if isinstance(t, dict) for k in PACKAGE_MANAGERS if k in t}
    errors = []
    for kind in sorted(kinds):
        pattern, example, what = PACKAGE_MANAGERS[kind]
        if not any(isinstance(p, str) and pattern.match(p) for p in packages):
            errors.append(f"{where}: {kind} tools need {what} in packages, such as "
                          f"'- {example}'. Add it, or remove the {kind} tools.")
    return errors


# What is installed

def workstation_npm_installed(npm_ls_json):
    """{name: version} from `npm ls -g --depth=0 --json`."""
    try:
        data = json.loads(npm_ls_json or "{}")
    except ValueError:
        return {}
    deps = data.get("dependencies") or {}
    return {name: info.get("version", "") for name, info in deps.items() if isinstance(info, dict)}


def workstation_uv_installed(uv_tool_list):
    """{normalized name: version} from `uv tool list`, whose tool lines
    look like "ruff v0.8.4" (with "- ruff" lines for their commands)."""
    found = {}
    for line in (uv_tool_list or "").splitlines():
        match = re.match(r"^(\S+) v(\S+)", line)
        if match:
            found[pypi_normalize(match.group(1))] = match.group(2)
    return found


# Decisions

def _normalize(tool):
    """A tool entry in the form the install record keeps."""
    kind = next(k for k in KINDS if k in tool)
    entry = {"kind": kind, "name": tool[kind]}
    if kind in ("npm", "uv"):
        entry["version"] = tool.get("version")
    if kind == "uv":
        entry["with"] = list(tool.get("with") or [])
        entry["python"] = tool.get("python")
    if kind == "curl":
        entry["creates"] = tool["creates"]
    return entry


def _key(entry):
    if entry["kind"] == "uv":
        return ("uv", pypi_normalize(entry["name"]))
    return (entry["kind"], entry["name"])


def _home_path(home, path):
    return home.rstrip("/") + path[1:] if path.startswith("~/") else path


def _script(home, url):
    return f"{home.rstrip('/')}/{SCRIPT_DIR}/{hashlib.sha256(url.encode()).hexdigest()[:16]}.sh"


def _argv(action, entry, home):
    kind, name = entry["kind"], entry["name"]
    if kind == "npm":
        if action == "uninstall":
            return ["npm", "uninstall", "--global", name]
        target = name + (f"@{entry['version']}" if entry["version"] else
                         "@latest" if action == "upgrade" else "")
        return ["npm", "install", "--global", "--no-fund", "--no-audit", target]
    if kind == "uv":
        if action == "uninstall":
            return ["uv", "tool", "uninstall", pypi_normalize(name)]
        if action == "upgrade":
            return ["uv", "tool", "upgrade", pypi_normalize(name)]
        argv = ["uv", "tool", "install"]
        if action == "reinstall":
            argv.append("--reinstall")
        if entry["python"]:
            argv += ["--python", entry["python"]]
        for w in entry["with"]:
            argv += ["--with", w]
        argv.append(name + (f"=={entry['version']}" if entry["version"] else ""))
        return argv
    return ["bash", _script(home, name)]


def workstation_tool_actions(tools, record, installed, upgrade, home):
    """What to do for each tool, in order: a list of
    {action, entry, argv, reason, script, creates}.

    tools      settings.tools (already checked)
    record     the entries the deploy installed last time
               (~/.local/state/nixlab/tools.json), or []
    installed  {"npm": {name: version}, "uv": {name: version},
                "curl": {url: True if its creates path exists},
                "available": {"npm": bool, "uv": bool}}
    upgrade    -e workstation_upgrade=true
    home       the user's home folder

    action is one of install, reinstall, upgrade, uninstall, keep (nothing
    to do) or leave (a removed tool the deploy can't uninstall).
    """
    entries = [_normalize(t) for t in tools]
    recorded = {_key(e): e for e in (record or []) if isinstance(e, dict) and "kind" in e}
    available = installed.get("available", {})
    actions = []

    def add(action, entry, reason):
        item = {"action": action, "entry": entry, "reason": reason, "argv": None,
                "script": None, "creates": None}
        if action not in ("keep", "leave"):
            item["argv"] = _argv(action, entry, home)
        if entry["kind"] == "curl":
            item["script"] = _script(home, entry["name"])
            item["creates"] = _home_path(home, entry["creates"])
        actions.append(item)

    for entry in entries:
        kind, key = entry["kind"], _key(entry)
        before = recorded.get(key)
        if kind == "curl":
            if not installed.get("curl", {}).get(entry["name"]):
                add("install", entry, f"{entry['creates']} is missing")
            elif upgrade:
                add("install", entry, "upgrade: running the script again")
            else:
                add("keep", entry, "installed")
            continue

        version = installed.get(kind, {}).get(key[1])
        pinned = entry["version"]
        if version is None:
            add("install", entry, "not installed")
        elif pinned and version != pinned:
            add("reinstall" if kind == "uv" else "install", entry,
                f"at {version}, pinned to {pinned}")
        elif kind == "uv" and (
                (before is None and (entry["with"] or entry["python"]))
                or (before is not None and (before.get("with") or [], before.get("python"))
                    != (entry["with"], entry["python"]))):
            add("reinstall", entry, "with: or python: changed")
        elif upgrade and not pinned:
            add("upgrade", entry, f"upgrade from {version}")
        else:
            add("keep", entry, f"at {version}")

    current = {_key(e) for e in entries}
    for key, entry in recorded.items():
        if key in current:
            continue
        kind = entry["kind"]
        if kind == "curl":
            add("leave", entry, "removed from the list; its files stay, as the deploy "
                                "doesn't know what the script wrote")
        elif not available.get(kind):
            add("leave", entry, f"removed from the list, but {kind} isn't installed anymore "
                                f"to uninstall it")
        elif key[1] in installed.get(kind, {}):
            add("uninstall", entry, "removed from the list")
    return actions


def workstation_tool_record(tools):
    """The install record to keep after a deploy: the listed tools."""
    return [_normalize(t) for t in tools]


def workstation_pin_errors(tools, installed):
    """Pinned npm and uv tools that aren't at their version after the
    deploy, as messages."""
    errors = []
    for entry in map(_normalize, tools):
        if entry["kind"] == "curl" or not entry["version"]:
            continue
        version = installed.get(entry["kind"], {}).get(_key(entry)[1])
        if version != entry["version"]:
            errors.append(f"{entry['kind']}: {entry['name']} is at {version or 'nothing'}, "
                          f"pinned to {entry['version']}.")
    return errors


def workstation_tool_versions(tools, installed):
    """One line per npm and uv tool: its name and installed version."""
    lines = []
    for entry in map(_normalize, tools):
        if entry["kind"] == "curl":
            lines.append(f"curl: {entry['name']} ({entry['creates']})")
            continue
        version = installed.get(entry["kind"], {}).get(_key(entry)[1], "not installed")
        pin = " (pinned)" if entry["version"] else ""
        lines.append(f"{entry['kind']}: {entry['name']} {version}{pin}")
    return lines


class FilterModule:
    def filters(self):
        return {
            "workstation_tools_errors": workstation_tools_errors,
            "workstation_secret_env": workstation_secret_env,
            "workstation_env_errors": workstation_env_errors,
            "workstation_env_file": workstation_env_file,
            "workstation_package_manager_errors": workstation_package_manager_errors,
            "workstation_npm_installed": workstation_npm_installed,
            "workstation_uv_installed": workstation_uv_installed,
            "workstation_tool_actions": workstation_tool_actions,
            "workstation_tool_record": workstation_tool_record,
            "workstation_pin_errors": workstation_pin_errors,
            "workstation_tool_versions": workstation_tool_versions,
        }
