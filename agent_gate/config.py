"""The repository's agent-gate.toml, read with the standard library (tomllib, Python 3.11+).

At push time the configuration is read from the BASE commit, not from the commit being judged: a push cannot relax the
rules it is judged by (the same idea as the secrets allowlist). When the base has no configuration yet (the push that
adds it), the file of the pushed tree is used. A configuration that does not parse is a problem, never "no rules".
"""
import pathlib, subprocess, tomllib

FILE = "agent-gate.toml"
ALL_CHECKS = ("secrets", "commits", "signatures", "language", "supply_chain", "pinned_models", "hidden_text",
              "telemetry_flags", "core_sync", "changes", "required_text", "gate_wiring")


class ConfigError(Exception):
    pass


def parse(text, where):
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{where}: {FILE} does not parse: {e}") from None
    if not isinstance(data, dict):
        raise ConfigError(f"{where}: {FILE} is not a table")
    return data


def from_tree(root):
    """The configuration in the work tree at root, or {} when there is none."""
    p = pathlib.Path(root) / FILE
    return parse(p.read_text(encoding="utf-8"), str(p)) if p.is_file() else {}


def from_ref(root, ref):
    """The configuration as committed in ref, or None when ref has no such file."""
    r = subprocess.run(["git", "show", f"{ref}:{FILE}"], cwd=root, capture_output=True)
    if r.returncode != 0:
        return None
    return parse(r.stdout.decode("utf-8", errors="replace"), f"{ref}")


def load(root, ref=None):
    """Returns (config, source). With ref, the committed file of ref wins; the work tree is the fallback."""
    if ref:
        cfg = from_ref(root, ref)
        if cfg is not None:
            return cfg, f"{FILE} at {ref[:12]}"
    cfg = from_tree(root)
    return cfg, (f"{FILE} in the work tree" if cfg else "built-in defaults (no agent-gate.toml)")


def section(cfg, name):
    value = (cfg or {}).get(name) or {}
    if not isinstance(value, dict):
        raise ConfigError(f"[{name}] must be a table")
    return value


def enabled(cfg):
    names = section(cfg, "checks").get("enabled", list(ALL_CHECKS))
    unknown = [n for n in names if n not in ALL_CHECKS]
    if unknown:
        raise ConfigError(f"[checks] enabled names unknown checks: {unknown}")
    return [n for n in ALL_CHECKS if n in names]


def get(cfg, dotted, default=None):
    """A value by a dotted name such as push.branches."""
    node = cfg or {}
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node
