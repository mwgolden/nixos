"""Decides where a host's secrets come from when its network has an
OpenBao host: the secrets/<network>/<host>.env file, OpenBao, or both.

Used from roles/host_secrets:

    {{ file_values | host_secrets_decide(store_values, file_exists, store_exists, push) }}

The rules (docs/plans/completed/OPENBAO-SECRETS.md, section 1): once a secret is in
OpenBao, that is where it is read from. A file is imported when OpenBao
has nothing yet. A file that differs from OpenBao stops the deploy, unless
push is set (-e secrets_push=true); then the file overwrites OpenBao.

Nothing here returns a value: differences are reported by key name only,
so they can go into messages.
"""


def host_secrets_diff(file_values, store_values):
    """Names of the keys whose values differ between the file and OpenBao,
    including keys only one of them has. Sorted, names only."""
    a, b = file_values or {}, store_values or {}
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


def host_secrets_decide(file_values, store_values, file_exists, store_exists, push=False):
    """What the deploy does, given the file's values (if file_exists) and
    OpenBao's (if store_exists). Returns:
      action   missing   neither has the secrets
               read      use OpenBao's (the file is absent or the same)
               import    OpenBao has nothing: write the file's values there
               push      they differ and push is set: overwrite OpenBao
               conflict  they differ and push isn't set: stop
      source   where the values the deploy uses came from: openbao,
               imported or pushed (the file's values, now also in OpenBao);
               "" when missing
      write    whether to write the file's values to OpenBao
      differ   the keys that differ (conflict and push), names only
    """
    file_values = file_values if file_exists else None
    store_values = store_values if store_exists else None
    if file_values is None and store_values is None:
        return {"action": "missing", "source": "", "write": False, "differ": []}
    if file_values is None:
        return {"action": "read", "source": "openbao", "write": False, "differ": []}
    if store_values is None:
        return {"action": "import", "source": "imported", "write": True, "differ": []}
    differ = host_secrets_diff(file_values, store_values)
    if not differ:
        return {"action": "read", "source": "openbao", "write": False, "differ": []}
    if push:
        return {"action": "push", "source": "pushed", "write": True, "differ": differ}
    return {"action": "conflict", "source": "", "write": False, "differ": differ}


class FilterModule:
    def filters(self):
        return {
            "host_secrets_diff": host_secrets_diff,
            "host_secrets_decide": host_secrets_decide,
        }
