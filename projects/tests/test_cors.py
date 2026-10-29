from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase


@override_settings(CORS_ALLOWED_ORIGINS=["http://localhost:5173"])
class CorsPreflightTests(APITestCase):
    def setUp(self):
        self.list_url = reverse("projects-list")

    def test_allowed_origin_preflight_bypasses_auth(self):
        response = self.client.options(
            self.list_url,
            HTTP_ORIGIN="http://localhost:5173",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization,content-type",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.headers.get("access-control-allow-origin"),
            "http://localhost:5173",
        )

    def test_unlisted_origin_preflight_does_not_get_cors_allow_origin(self):
        response = self.client.options(
            self.list_url,
            HTTP_ORIGIN="http://evil.example",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization,content-type",
        )

        self.assertNotIn("access-control-allow-origin", response.headers)

    def test_get_projects_without_auth_still_requires_authentication(self):
        response = self.client.get(
            self.list_url,
            HTTP_ORIGIN="http://localhost:5173",
        )

        self.assertIn(
            response.status_code,
            (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )
