"""Tests for contacts.delete tool.

Uses TransactionTestCase so sync_to_async worker threads can see committed rows.
"""

from backend.testing import run_async
import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase, TransactionTestCase

from contacts.models import Contact

User = get_user_model()


def _run(coro):
    return run_async(coro)


class ContactsDeleteTests(TransactionTestCase):
    def setUp(self):
        self.uid = str(uuid.uuid4())
        self.user = User.objects.create_user(
            email=f"{self.uid}@test.com", supabase_uid=self.uid
        )

    def _create_contact(self, first="Alice", last="Smith"):
        return Contact.objects.create(
            user=self.user,
            first_name=first,
            last_name=last,
        )

    def test_delete_removes_contact_from_db(self):
        from tools.contacts.api import contacts_delete

        contact = self._create_contact()
        pk = contact.pk

        result = _run(contacts_delete(user_id=self.uid, contact_id=pk))

        self.assertTrue(result["deleted"])
        self.assertEqual(result["contact"]["id"], pk)
        self.assertFalse(Contact.objects.filter(pk=pk).exists())

    def test_delete_wrong_user_raises(self):
        from tools.contacts.api import contacts_delete

        other_uid = str(uuid.uuid4())
        other = User.objects.create_user(email=f"{other_uid}@test.com", supabase_uid=other_uid)
        contact = Contact.objects.create(user=other, first_name="Bob")

        with self.assertRaises(Contact.DoesNotExist):
            _run(contacts_delete(user_id=self.uid, contact_id=contact.pk))

    def test_delete_nonexistent_raises(self):
        from tools.contacts.api import contacts_delete

        with self.assertRaises(Contact.DoesNotExist):
            _run(contacts_delete(user_id=self.uid, contact_id=99999))


class ContactsDeleteRegistrationTests(TestCase):
    def test_contacts_delete_registered(self):
        from tools.registry import _REGISTRY
        self.assertIn("contacts.delete", _REGISTRY)

    def test_contacts_delete_requires_confirmation(self):
        from tools.registry import _REGISTRY
        self.assertTrue(_REGISTRY["contacts.delete"].requires_confirmation)
