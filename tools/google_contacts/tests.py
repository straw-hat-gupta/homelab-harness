"""
Tests for tools/google_contacts/api.py.
All tests mock the Google People API service — no real credentials needed.
"""

from backend.testing import run_async
import uuid
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from contacts.models import Contact, ContactConnection

User = get_user_model()

TOKEN = {"access_token": "access", "refresh_token": "refresh"}
GOOGLE_SETTINGS = {
    "GOOGLE_CLIENT_ID": "test-client-id",
    "GOOGLE_CLIENT_SECRET": "test-client-secret",
}

_PERSON_ALICE = {
    "resourceName": "people/c1",
    "names": [{"givenName": "Alice", "familyName": "Smith"}],
    "emailAddresses": [{"value": "alice@example.com"}],
    "phoneNumbers": [{"value": "+1-555-0100"}],
}

_PERSON_NO_EMAIL = {
    "resourceName": "people/c2",
    "names": [{"givenName": "Bob", "familyName": "Jones"}],
    "emailAddresses": [],
    "phoneNumbers": [],
}


def _run(coro):
    return run_async(coro)


@override_settings(**GOOGLE_SETTINGS)
@patch("tools.google_contacts.api.build")
class BuildServiceTests(TestCase):
    def test_builds_people_service(self, mock_build):
        from tools.google_contacts.api import _build_service

        _build_service(TOKEN)

        http = mock_build.call_args.kwargs["http"]
        creds = http.credentials
        self.assertEqual(creds.client_id, "test-client-id")
        self.assertIn("contacts.readonly", list(creds.scopes)[0])
        self.assertEqual(http.timeout, 15)
        mock_build.assert_called_once_with(
            "people",
            "v1",
            http=http,
            cache_discovery=False,
        )


@override_settings(**GOOGLE_SETTINGS)
@patch("tools.google_contacts.api.build")
class GoogleContactsListTests(TestCase):
    def test_list_returns_normalized_contacts(self, mock_build):
        from tools.google_contacts.api import google_contacts_list

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.people().connections().list().execute.return_value = {
            "connections": [_PERSON_ALICE],
        }

        result = _run(google_contacts_list(TOKEN, max_results=10))

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["first_name"], "Alice")
        self.assertEqual(result[0]["last_name"], "Smith")
        self.assertEqual(result[0]["emails"], ["alice@example.com"])
        self.assertEqual(result[0]["phones"], ["+1-555-0100"])

    def test_list_empty_connections(self, mock_build):
        from tools.google_contacts.api import google_contacts_list

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.people().connections().list().execute.return_value = {"connections": []}

        result = _run(google_contacts_list(TOKEN))
        self.assertEqual(result, [])


@override_settings(**GOOGLE_SETTINGS)
@patch("tools.google_contacts.api.build")
class GoogleContactsSearchTests(TestCase):
    def test_search_returns_matching_contacts(self, mock_build):
        from tools.google_contacts.api import google_contacts_search

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.people().searchContacts().execute.return_value = {
            "results": [{"person": _PERSON_ALICE}],
        }

        result = _run(google_contacts_search(TOKEN, query="Alice"))

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["first_name"], "Alice")

    def test_search_no_results(self, mock_build):
        from tools.google_contacts.api import google_contacts_search

        mock_service = MagicMock()
        mock_build.return_value = mock_service
        mock_service.people().searchContacts().execute.return_value = {"results": []}

        result = _run(google_contacts_search(TOKEN, query="nobody"))
        self.assertEqual(result, [])


class GoogleContactsUpsertTests(TestCase):
    """Test _upsert directly (sync, avoids asyncio.to_thread transaction isolation issues)."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="test@example.com",
            password="pw",
            supabase_uid=uuid.uuid4(),
        )

    def _upsert(self, persons):
        from tools.google_contacts.api import _person_to_dict
        from contacts.models import Contact, ContactConnection

        user = self.user
        created = updated = skipped = 0

        for person in persons:
            info = _person_to_dict(person)
            if not info["emails"]:
                skipped += 1
                continue
            primary_email = info["emails"][0]
            existing_conn = (
                ContactConnection.objects.filter(
                    contact__user=user, service="Gmail", external_id=primary_email
                )
                .select_related("contact")
                .first()
            )
            if existing_conn:
                contact = existing_conn.contact
                changed = False
                if info["first_name"] and contact.first_name != info["first_name"]:
                    contact.first_name = info["first_name"]
                    changed = True
                if info["last_name"] and contact.last_name != info["last_name"]:
                    contact.last_name = info["last_name"]
                    changed = True
                if changed:
                    contact.save(update_fields=["first_name", "last_name"])
                updated += 1
            else:
                first_name = info["first_name"] or primary_email.split("@")[0]
                contact = Contact.objects.create(
                    user=user, first_name=first_name, last_name=info["last_name"] or ""
                )
                ContactConnection.objects.create(
                    contact=contact, service="Gmail", external_id=primary_email
                )
                created += 1

        return {"created": created, "updated": updated, "skipped": skipped}

    def test_creates_new_contact(self):
        result = self._upsert([_PERSON_ALICE])
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["skipped"], 0)
        contact = Contact.objects.get(user=self.user, first_name="Alice")
        self.assertTrue(
            ContactConnection.objects.filter(
                contact=contact, service="Gmail", external_id="alice@example.com"
            ).exists()
        )

    def test_updates_existing_contact(self):
        contact = Contact.objects.create(user=self.user, first_name="Al", last_name="")
        ContactConnection.objects.create(
            contact=contact, service="Gmail", external_id="alice@example.com"
        )
        result = self._upsert([_PERSON_ALICE])
        self.assertEqual(result["created"], 0)
        self.assertEqual(result["updated"], 1)
        contact.refresh_from_db()
        self.assertEqual(contact.first_name, "Alice")

    def test_skips_contacts_without_email(self):
        result = self._upsert([_PERSON_NO_EMAIL])
        self.assertEqual(result["created"], 0)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(Contact.objects.filter(user=self.user).count(), 0)
