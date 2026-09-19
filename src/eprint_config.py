"""Configuration for the DKU ePrint backend.

The CUPS backend runs as the 'lp' user, so it cannot read a NetID out of the
printing user's home directory.  Everything therefore lives in one
system-readable file, /etc/dku-eprint/eprint.conf:

    # default for everyone
    netid = abc123

    # per Unix account overrides, for shared machines
    [users]
    alice = abc123
    guest = xyz789

Values are also accepted from the environment (DKU_EPRINT_NETID), which is
mainly useful for testing.
"""

import os
import re

# A NetID ends up in the LPD control file, one field per line, so anything with
# a newline in it could forge extra control lines.  Keep it to what a NetID
# actually is.
NETID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def valid_netid(value):
    return bool(value) and bool(NETID_RE.match(value.strip()))


CONFIG_PATHS = [
    os.environ.get("DKU_EPRINT_CONFIG") or "",
    "/etc/dku-eprint/eprint.conf",
    os.path.expanduser("~/.config/dku-eprint/eprint.conf"),
]

DEFAULTS = {
    "server": "dku-ep-ps2-pap1.oit.duke.edu",
    "netid": "",
    "hostname": "",
    # never  -- always use the stored netid (set once at install)
    # always -- ask in a desktop dialog for every job, via dku-eprint-agent
    "prompt": "never",
}


def config_path():
    """The file we would write to: the first existing one, else the system one."""
    for path in CONFIG_PATHS:
        if path and os.path.exists(path):
            return path
    return "/etc/dku-eprint/eprint.conf"


def load_config(path=None):
    """Parse the config file.  Unknown keys are kept; missing file is not an error."""
    cfg = dict(DEFAULTS)
    cfg["users"] = {}

    paths = [path] if path else CONFIG_PATHS
    for candidate in paths:
        if not candidate or not os.path.exists(candidate):
            continue
        section = None
        try:
            with open(candidate, "r") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or line.startswith(";"):
                        continue
                    if line.startswith("[") and line.endswith("]"):
                        section = line[1:-1].strip().lower()
                        continue
                    key, sep, value = line.partition("=")
                    if not sep:
                        continue
                    key = key.strip()
                    value = value.strip()
                    if section == "users":
                        cfg["users"][key] = value
                    else:
                        cfg[key.lower()] = value
        except OSError:
            continue
        break

    env = os.environ.get("DKU_EPRINT_NETID")
    if env:
        cfg["netid"] = env
    return cfg


def netid_for(cfg, unix_user):
    """Per user override wins over the global default."""
    if unix_user and cfg.get("users", {}).get(unix_user):
        return cfg["users"][unix_user].strip()
    return (cfg.get("netid") or "").strip()


def write_config(cfg, path=None):
    path = path or config_path()
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory, 0o755)

    lines = [
        "# DKU ePrint configuration",
        "# Managed by dku-eprint(1); hand edits are preserved on rewrite.",
        "",
        "server = %s" % cfg.get("server", DEFAULTS["server"]),
        "netid = %s" % cfg.get("netid", ""),
        "",
        "# never  = always use the netid above",
        "# always = ask in a desktop dialog for every job",
        "prompt = %s" % cfg.get("prompt", DEFAULTS["prompt"]),
    ]
    if cfg.get("hostname"):
        lines.append("hostname = %s" % cfg["hostname"])
    users = cfg.get("users") or {}
    if users:
        lines += ["", "[users]"]
        lines += ["%s = %s" % (k, v) for k, v in sorted(users.items())]
    lines.append("")

    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        fh.write("\n".join(lines))
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)
    return path
