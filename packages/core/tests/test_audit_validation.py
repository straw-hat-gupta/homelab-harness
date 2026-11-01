import pytest

from homelab_harness.audit.validation import DATA_MAX_BYTES, STRING_MAX, validate_audit_input
from homelab_harness_sdk.errors import InvalidInput


def _validate(**overrides):
    fields = {
        "kind": "plan.created",
        "actor": "owner",
        "plan_id": None,
        "job_id": None,
        "target": None,
        "data": None,
    }
    return validate_audit_input(**(fields | overrides))


def test_minimal_event_is_valid_with_empty_data():
    valid = _validate()
    assert valid.kind == "plan.created"
    assert valid.data == {}


@pytest.mark.parametrize("kind", ["plan.created", "job.step.finished", "secret.ssh_sign.used"])
def test_dotted_kinds_are_accepted(kind):
    assert _validate(kind=kind).kind == kind


@pytest.mark.parametrize("kind", ["", "plan", "Plan.created", "plan..created", "plan.", "a." * 40])
def test_malformed_kinds_are_rejected(kind):
    with pytest.raises(InvalidInput, match="kind"):
        _validate(kind=kind)


@pytest.mark.parametrize("actor", ["owner", "system", "client:claude-code", "client:chatgpt.dev"])
def test_known_actor_forms_are_accepted(actor):
    assert _validate(actor=actor).actor == actor


@pytest.mark.parametrize("actor", ["", "root", "client:", "client: spaces", "x" * 200])
def test_unknown_actor_forms_are_rejected(actor):
    with pytest.raises(InvalidInput, match="actor"):
        _validate(actor=actor)


@pytest.mark.parametrize("field", ["plan_id", "job_id", "target"])
def test_references_must_be_identifiers(field):
    assert getattr(_validate(**{field: "pve1/node-a:100"}), field) == "pve1/node-a:100"
    with pytest.raises(InvalidInput, match=field):
        _validate(**{field: "rm -rf /"})


def test_data_is_normalized_to_plain_json():
    valid = _validate(data={"disks": ("sda", "sdb"), "count": 2, "ok": True, "ratio": 0.5})
    assert valid.data == {"disks": ["sda", "sdb"], "count": 2, "ok": True, "ratio": 0.5}


@pytest.mark.parametrize(
    "data",
    [
        {"Bad-Key": 1},
        {1: "non-string key"},
        {"blob": b"bytes"},
        {"when": object()},
        {"ratio": float("nan")},
        {"note": "x" * (STRING_MAX + 1)},
        {"a": {"b": {"c": {"d": 1}}}},
        {"a": {"b": [[1]]}},
        {f"k{i}": "x" * 200 for i in range(DATA_MAX_BYTES // 200 + 1)},
    ],
)
def test_payload_shaped_data_is_rejected(data):
    with pytest.raises(InvalidInput):
        _validate(data=data)


def test_error_messages_never_echo_the_value():
    with pytest.raises(InvalidInput) as excinfo:
        _validate(target="hunter2 secret value")
    assert "hunter2" not in excinfo.value.safe_message
