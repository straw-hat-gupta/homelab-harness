import pytest

from homelab_harness_sdk import (
    AmbiguousOutcome,
    AuthRejected,
    HarnessError,
    RateLimited,
    RetryClass,
    TargetUnavailable,
    Tier,
)


def test_tiers_are_ordered():
    assert Tier.T0 < Tier.T1 < Tier.T2 < Tier.T3
    assert max(Tier.T1, Tier.T3) is Tier.T3


@pytest.mark.parametrize(
    ("retry_class", "may_retry"),
    [(RetryClass.READ, True), (RetryClass.IDEMPOTENT, True), (RetryClass.UNSAFE, False)],
)
def test_only_unsafe_steps_are_never_retried(retry_class, may_retry):
    assert retry_class.may_retry is may_retry


def test_transient_errors_are_retryable_and_definitive_ones_are_not():
    assert TargetUnavailable("down").retryable
    assert RateLimited("slow down", retry_after_seconds=2.0).retryable
    assert not AuthRejected("revoked").retryable
    # An ambiguous outcome must never be treated as retryable (S6).
    assert not AmbiguousOutcome("timed out after send").retryable


def test_errors_carry_safe_message_and_target():
    err = RateLimited("slow down", target="pve1", retry_after_seconds=3)
    assert isinstance(err, HarnessError)
    assert err.safe_message == "slow down"
    assert err.target == "pve1"
    assert err.retry_after_seconds == 3
    assert str(err) == "slow down"
