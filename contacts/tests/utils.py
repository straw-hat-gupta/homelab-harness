import uuid

from django.urls import reverse
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

OPENAI_KEY = settings.OPENAI_KEY

User = get_user_model()

class ModelTests(APITestCase):
    @classmethod
    def setUpTestData(self):
        """
        Set up test data for the test suite.
        """
        self.user = User.objects.create_user(
            email='testuser@example.com',
            password='testpassword123',
            supabase_uid=uuid.uuid4(),
        )

    def setUp(self):
        """
        Set up test data and client for each test.
        """
        # Log in the user and get the access token
        login_url = reverse('login')
        response = self.client.post(login_url, {
            'email': 'testuser@example.com',
            'password': 'testpassword123'
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.access_token = response.data['access']
