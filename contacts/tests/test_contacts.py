import uuid

from contacts.models import Contact, ContactConnection
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase, APIClient

User = get_user_model()


class ContactTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create(
            email="test@example.com",
            supabase_uid=uuid.uuid4(),
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def _create_contact(self, first_name, last_name, alias=None):
        return Contact.objects.create(
            user=self.user, first_name=first_name, last_name=last_name, alias=alias
        )

    def _create_connection(self, contact, service, external_id, metadata=None):
        return ContactConnection.objects.create(
            contact=contact, service=service, external_id=external_id, metadata=metadata
        )

    # ---------- Auth ----------

    def test_unauthenticated_returns_4xx(self):
        self.client.force_authenticate(user=None)
        response = self.client.get(reverse("contact-list"))
        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    # ---------- CRUD ----------

    def test_get_contacts_empty(self):
        response = self.client.get(reverse("contact-list"))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["results"], [])

    def test_get_contacts_returns_own(self):
        self._create_contact("John", "Doe")
        self._create_contact("Jane", "Smith")
        response = self.client.get(reverse("contact-list"))
        self.assertEqual(len(response.data["results"]), 2)

    def test_contacts_scoped_to_user(self):
        other = User.objects.create(
            email="other@example.com",
            supabase_uid=uuid.uuid4(),
        )
        Contact.objects.create(user=other, first_name="Other", last_name="User")
        response = self.client.get(reverse("contact-list"))
        self.assertEqual(response.data["results"], [])

    def test_search_contacts(self):
        self._create_contact("John", "Doe")
        self._create_contact("Jon", "Doe")
        self._create_contact("Jane", "Smith")
        self._create_contact("Alice", "Doe")
        self._create_contact("Michael", "John")
        self._create_contact("Joan", "Smith")

        url = reverse("contact-list")
        self.assertEqual(len(self.client.get(f"{url}?search=John").data["results"]), 2)
        self.assertEqual(len(self.client.get(f"{url}?search=Doe").data["results"]), 3)
        self.assertEqual(len(self.client.get(f"{url}?search=Jo").data["results"]), 4)
        self.assertEqual(len(self.client.get(f"{url}?search=Smith").data["results"]), 2)

    def test_get_contact(self):
        contact = self._create_contact("John", "Doe")
        url = reverse("contact-detail", kwargs={"contactId": contact.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["first_name"], "John")

    def test_create_contact(self):
        data = {"first_name": "Test", "last_name": "User", "alias": "Tester"}
        response = self.client.post(reverse("contact-list"), data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["first_name"], "Test")
        self.assertEqual(response.data["alias"], "Tester")

    def test_update_contact(self):
        contact = self._create_contact("John", "Doe")
        url = reverse("contact-detail", kwargs={"contactId": contact.id})
        response = self.client.put(url, {"first_name": "Johnny"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["first_name"], "Johnny")

    def test_delete_contact(self):
        contact = self._create_contact("John", "Doe")
        url = reverse("contact-detail", kwargs={"contactId": contact.id})
        self.assertEqual(self.client.delete(url).status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(self.client.get(url).status_code, status.HTTP_404_NOT_FOUND)

    # ---------- Connections ----------

    def test_create_valid_contact_connection(self):
        contact = self._create_contact("John", "Doe")
        url = reverse("contact-connection-list", kwargs={"contactId": contact.id})
        response = self.client.post(url, {"service": "Gmail", "external_id": "johndoe@gmail.com"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["service"], "Gmail")

    def test_create_invalid_contact_connection(self):
        contact = self._create_contact("John", "Doe")
        url = reverse("contact-connection-list", kwargs={"contactId": contact.id})
        response = self.client.post(url, {"service": "Twitter", "external_id": "12345"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_update_contact_connection(self):
        contact = self._create_contact("John", "Doe")
        conn = self._create_connection(contact, "Gmail", "johndoe@gmail.com")
        url = reverse("contact-connection-detail", kwargs={"contactId": contact.id, "connectionId": conn.id})
        response = self.client.put(url, {"service": "Gmail", "external_id": "johndoe1@gmail.com"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["external_id"], "johndoe1@gmail.com")

    def test_delete_contact_connection(self):
        contact = self._create_contact("John", "Doe")
        conn = self._create_connection(contact, "Gmail", "johndoe@gmail.com")
        url = reverse("contact-connection-detail", kwargs={"contactId": contact.id, "connectionId": conn.id})
        response = self.client.delete(url, {"service": "Gmail"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
