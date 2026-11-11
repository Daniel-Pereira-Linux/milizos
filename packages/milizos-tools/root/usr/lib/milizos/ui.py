# MilizOS - utilitarios de terminal compartilhados pelos modulos do comando nos
import os
import subprocess
import sys

AUTHOR = "Daniel Pereira da Silva"
AUTHOR_URL = "https://www.linkedin.com/in/danielpereira-linux/"
C = sys.stdout.isatty()


def col(s, c):
    return f"\033[{c}m{s}\033[0m" if C else s


ac = lambda s: col(s, "38;2;0;240;200")
dim = lambda s: col(s, "2")
ok = lambda s: col(s, "32")
bad = lambda s: col(s, "31")
warn = lambda s: col(s, "33")


def sh(cmd, timeout=60):
    try:
        p = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, timeout=timeout)
        return (p.stdout or p.stderr).strip()
    except (OSError, subprocess.SubprocessError) as e:
        return f"(falhou: {e})"


def rc(cmd, timeout=60):
    try:
        return subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, timeout=timeout).returncode
    except (OSError, subprocess.SubprocessError):
        return 1


def need_root(argv_tail):
    """Reexecuta o comando com sudo quando preciso."""
    if os.geteuid() != 0:
        os.execvp("sudo", ["sudo", "/usr/bin/nos"] + list(argv_tail))


def osname():
    try:
        for l in open("/etc/os-release"):
            if l.startswith("PRETTY_NAME="):
                return l.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "MilizOS"
