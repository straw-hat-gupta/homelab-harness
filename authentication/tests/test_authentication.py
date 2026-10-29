import uuid
import time
from unittest.mock import patch

import jwt
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from authentication.authentication import (
    SupabaseUserSyncConflict,
    _decode_access_token,
    _sync_user_from_supabase_claims,
)

User = get_user_model()


def _token(secret: str, issuer: str, audience: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "iss": issuer,
            "aud": audience,
            "sub": str(uuid.uuid4()),
            "iat": now,
            "exp": now + 300,
        },
        secret,
        algorithm="HS256",
    )


class SupabaseTokenDecodeTests(TestCase):
    @override_settings(
        SUPABASE_JWT_SECRET="test-secret",
        SUPABASE_JWT_ISSUER="https://example.supabase.co/auth/v1",
        SUPABASE_JWT_AUDIENCE="authenticated",
    )
    def test_decodes_token_with_expected_audience(self):
        token = _token("test-secret", "https://example.supabase.co/auth/v1", "authenticated")

        payload = _decode_access_token(token)

        self.assertEqual(payload["aud"], "authenticated")

    @override_settings(
        SUPABASE_JWT_SECRET="test-secret",
        SUPABASE_JWT_ISSUER="https://example.supabase.co/auth/v1",
        SUPABASE_JWT_AUDIENCE="authenticated",
    )
    def test_rejects_token_with_wrong_audience(self):
        token = _token("test-secret", "https://example.supabase.co/auth/v1", "service_role")

        with self.assertRaises(jwt.InvalidAudienceError):
            _decode_access_token(token)

    @override_settings(
        SUPABASE_JWT_SECRET="test-secret",
        SUPABASE_JWT_ISSUER="https://example.supabase.co/auth/v1",
        SUPABASE_JWT_AUDIENCE="",
    )
    def test_blank_audience_setting_still_requires_authenticated_audience(self):
        token = _token("test-secret", "https://example.supabase.co/auth/v1", "authenticated")

        payload = _decode_access_token(token)

        self.assertEqual(payload["aud"], "authenticated")


class SupabaseUserSyncTests(TestCase):
    def test_supabase_uid_field_is_required(self):
        self.assertFalse(User._meta.get_field("supabase_uid").null)

    def test_create_user_requires_supabase_uid(self):
        with self.assertRaises(ValueError):
            User.objects.create_user(email="legacy@example.com")

    def test_existing_user_by_supabase_uid_is_returned(self):
        supabase_uid = uuid.uuid4()
        user = User.objects.create_user(
            email="existing@example.com",
            supabase_uid=supabase_uid,
        )

        synced = _sync_user_from_supabase_claims(str(supabase_uid), "existing@example.com")

        self.assertEqual(synced.pk, user.pk)

    def test_missing_uid_and_unclaimed_email_creates_new_user(self):
        supabase_uid = uuid.uuid4()

        synced = _sync_user_from_supabase_claims(str(supabase_uid), "new@example.com")

        self.assertEqual(synced.supabase_uid, supabase_uid)
        self.assertEqual(synced.email, "new@example.com")
        self.assertEqual(User.objects.count(), 1)

    def test_existing_email_with_different_non_null_uid_raises_conflict(self):
        User.objects.create_user(
            email="conflict@example.com",
            supabase_uid=uuid.uuid4(),
        )

        with self.assertRaises(SupabaseUserSyncConflict):
            _sync_user_from_supabase_claims(str(uuid.uuid4()), "conflict@example.com")

    def test_existing_uid_user_updates_email_when_unclaimed(self):
        supabase_uid = uuid.uuid4()
        user = User.objects.create_user(
            email="old@example.com",
            supabase_uid=supabase_uid,
        )

        synced = _sync_user_from_supabase_claims(str(supabase_uid), "new@example.com")

        user.refresh_from_db()
        self.assertEqual(synced.pk, user.pk)
        self.assertEqual(user.email, "new@example.com")

    def test_existing_uid_user_email_change_conflict_raises(self):
        supabase_uid = uuid.uuid4()
        user = User.objects.create_user(
            email="old@example.com",
            supabase_uid=supabase_uid,
        )
        other = User.objects.create_user(
            email="taken@example.com",
            supabase_uid=uuid.uuid4(),
        )

        with self.assertRaises(SupabaseUserSyncConflict):
            _sync_user_from_supabase_claims(str(supabase_uid), "taken@example.com")

        user.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual(user.email, "old@example.com")
        self.assertEqual(other.email, "taken@example.com")

    def test_missing_token_email_uses_synthetic_fallback(self):
        supabase_uid = uuid.uuid4()

        synced = _sync_user_from_supabase_claims(str(supabase_uid), None)

        self.assertEqual(synced.supabase_uid, supabase_uid)
        self.assertEqual(synced.email, f"{supabase_uid}@users.invalid")

    def test_email_is_normalized_before_create(self):
        incoming_uid = uuid.uuid4()

        synced = _sync_user_from_supabase_claims(str(incoming_uid), "User@EXAMPLE.COM")

        self.assertEqual(synced.supabase_uid, incoming_uid)
        self.assertEqual(synced.email, "User@example.com")

    def test_integrity_error_on_create_retries_via_reloaded_user(self):
        incoming_uid = uuid.uuid4()
        original_create_user = User.objects.create_user
        calls = {"count": 0}

        def flaky_create_user(*args, **kwargs):
            if calls["count"] == 0:
                calls["count"] += 1
                raise IntegrityError("duplicate key value violates unique constraint")
            return original_create_user(*args, **kwargs)

        with patch.object(User.objects, "create_user", side_effect=flaky_create_user):
            synced = _sync_user_from_supabase_claims(str(incoming_uid), "race@example.com")

        self.assertEqual(synced.supabase_uid, incoming_uid)
        self.assertEqual(synced.email, "race@example.com")
        self.assertEqual(calls["count"], 1)
        self.assertEqual(User.objects.count(), 1)


class SupabaseAuthenticationSmokeTests(APITestCase):
    def _auth_get(self, path: str, payload: dict):
        with patch("authentication.authentication._decode_access_token", return_value=payload):
            return self.client.get(
                path,
                HTTP_AUTHORIZATION="Bearer fake-token",
            )

    def test_projects_request_creates_user_with_supabase_uid(self):
        incoming_uid = str(uuid.uuid4())

        response = self._auth_get(
            reverse("projects-list"),
            {"sub": incoming_uid, "email": "legacy@example.com"},
        )

        self.assertEqual(response.status_code, 200)
        user = User.objects.get(email="legacy@example.com")
        self.assertEqual(str(user.supabase_uid), incoming_uid)

    def test_projects_request_rejects_conflicting_email_binding(self):
        existing_uid = uuid.uuid4()
        user = User.objects.create_user(
            email="conflict@example.com",
            supabase_uid=existing_uid,
        )
        incoming_uid = str(uuid.uuid4())

        response = self._auth_get(
            reverse("projects-list"),
            {"sub": incoming_uid, "email": "conflict@example.com"},
        )

        self.assertIn(response.status_code, (401, 403))
        user.refresh_from_db()
        self.assertEqual(user.supabase_uid, existing_uid)
        self.assertEqual(User.objects.count(), 1)
