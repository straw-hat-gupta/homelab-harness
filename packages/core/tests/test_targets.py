"""The targets file (interim): validation, secret-file rules, redaction, readiness."""

import ast
import logging
import secrets
from importlib.metadata import EntryPoint
from pathlib import Path

import pytest

from homelab_harness.capabilities import discover_capabilities
from homelab_harness.log_config import QUIET_LIBRARY_LOGGERS, configure_logging
from homelab_harness.redaction import MASK, Redactor
from homelab_harness.settings import Settings
from homelab_harness.targets import load_targets
from homelab_harness_sdk import InvalidInput

CORE_SRC = Path(__file__).parents[1] / "src"


@pytest.fixture(scope="module")
def capabilities():
    return discover_capabilities()


@pytest.fixture
def secret_value():
    return f"CANARY_TARGET_{secrets.token_hex(10)}"


@pytest.fixture
def secret_file(tmp_path, secret_value):
    path = tmp_path / "read.secret"
    path.write_text(secret_value, encoding="utf-8")
    path.chmod(0o400)
    return path


def write_targets(tmp_path, body):
    path = tmp_path / "targets.toml"
    path.write_text(body, encoding="utf-8")
    return path


def entry(secret_file, *, name="home", extra="", tier="read"):
    return f"""
[[proxmox]]
name = "{name}"
endpoints = ["pve1.lab.invalid:8006"]
tls = {{ kind = "pinned", sha256 = "{"AB" * 32}" }}
{extra}
[proxmox.credentials.{tier}]
token_id = "harness@pve!read"
token_secret_file = "{secret_file}"
"""


def test_loads_targets_and_registers_secrets(tmp_path, capabilities, secret_file, secret_value):
    scrubber = Redactor()
    path = write_targets(tmp_path, entry(secret_file) + entry(secret_file, name="lab"))
    registry = load_targets(path, capabilities, scrubber=scrubber)
    assert registry.names("proxmox") == ["home", "lab"]
    home = registry.get("proxmox", "home")
    assert home.credentials["read"].secret == secret_value
    assert secret_value not in repr(home)
    assert scrubber.scrub_text(f"x {secret_value} y") == f"x {MASK} y"


def test_target_selection(tmp_path, capabilities, secret_file):
    single = load_targets(write_targets(tmp_path, entry(secret_file)), capabilities)
    assert single.get("proxmox", None).name == "home"
    double = load_targets(
        write_targets(tmp_path, entry(secret_file) + entry(secret_file, name="lab")), capabilities
    )
    with pytest.raises(InvalidInput, match="choose one: home, lab"):
        double.get("proxmox", None)
    with pytest.raises(InvalidInput, match="unknown proxmox target"):
        double.get("proxmox", "CANARY_NAME")


@pytest.mark.parametrize("mode", [0o440, 0o404, 0o644, 0o600 | 0o020])
def test_secret_files_readable_by_others_are_refused(tmp_path, capabilities, secret_file, mode):
    secret_file.chmod(mode)
    with pytest.raises(InvalidInput, match="group or others"):
        load_targets(write_targets(tmp_path, entry(secret_file)), capabilities)


def test_owner_only_read_write_is_accepted(tmp_path, capabilities, secret_file):
    secret_file.chmod(0o600)
    assert load_targets(write_targets(tmp_path, entry(secret_file)), capabilities)


@pytest.mark.parametrize(
    ("body_of", "message"),
    [
        (lambda f: entry(Path("/nonexistent/secret")), "cannot be read"),
        (lambda f: entry(f, name="bad name!"), r"proxmox\[0\] is invalid: name"),
        (lambda f: entry(f, extra='insecure = "CANARY_VALUE"'), "insecure"),
        (lambda f: entry(f, tier="root"), "unknown credential tier"),
        (lambda f: entry(f) + entry(f), "unique"),
        (lambda f: entry(f).replace("[[proxmox]]", "[[truenas]]"), "not installed"),
        (lambda f: "proxmox = = CANARY_VALUE", "not valid TOML"),
        (lambda f: 'proxmox = "x"', "array of tables"),
    ],
)
def test_invalid_files_name_the_problem_not_the_value(
    tmp_path, capabilities, secret_file, body_of, message
):
    with pytest.raises(InvalidInput, match=message) as raised:
        load_targets(write_targets(tmp_path, body_of(secret_file)), capabilities)
    assert "CANARY_VALUE" not in raised.value.safe_message


def test_empty_secret_file_is_refused(tmp_path, capabilities, secret_file):
    secret_file.chmod(0o600)
    secret_file.write_text("\n", encoding="utf-8")
    with pytest.raises(InvalidInput, match="empty"):
        load_targets(write_targets(tmp_path, entry(secret_file)), capabilities)


def test_proxmox_is_discovered_through_its_entry_point(capabilities):
    assert "proxmox" in capabilities
    assert capabilities["proxmox"].tools


def test_discovery_rejects_non_capabilities_and_duplicates():
    bogus = EntryPoint(name="bogus", value="homelab_harness.settings:Settings", group="g")
    with pytest.raises(TypeError, match=r"not a homelab_harness_sdk\.Capability"):
        discover_capabilities((bogus,))
    proxmox = EntryPoint(
        name="proxmox", value="homelab_harness_proxmox.capability:CAPABILITY", group="g"
    )
    again = EntryPoint(
        name="proxmox2", value="homelab_harness_proxmox.capability:CAPABILITY", group="g"
    )
    with pytest.raises(ValueError, match="registered twice"):
        discover_capabilities((proxmox, again))


def test_core_never_imports_a_capability_package():
    # Capabilities are reached only through entry points (extending.md).
    offenders = []
    for path in CORE_SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            offenders += [f"{path.name}: {n}" for n in names if n.startswith("homelab_harness_")]
    allowed = ("homelab_harness_sdk",)
    assert [o for o in offenders if not o.split(": ")[1].startswith(allowed)] == []


def test_http_client_request_logs_are_held_at_warning():
    # httpx logs reason phrases, which Proxmox fills with its error text (R-16).
    configure_logging(Settings())
    try:
        for name in QUIET_LIBRARY_LOGGERS:
            assert logging.getLogger(name).getEffectiveLevel() == logging.WARNING
    finally:
        logging.getLogger().handlers.clear()
        for name in QUIET_LIBRARY_LOGGERS:
            logging.getLogger(name).setLevel(logging.NOTSET)
