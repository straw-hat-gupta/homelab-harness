import httplib2
from google_auth_httplib2 import AuthorizedHttp


GOOGLE_API_TIMEOUT_SECONDS = 15


def authorized_http(credentials, timeout: int = GOOGLE_API_TIMEOUT_SECONDS):
    """Build a Google API HTTP transport with an explicit request timeout."""
    return AuthorizedHttp(credentials, http=httplib2.Http(timeout=timeout))
