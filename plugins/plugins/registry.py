# Canonical registry of all supported plugins.
# All plugin IDs, display labels, OAuth config, and contact service names are derived here.
PLUGIN_REGISTRY = {
    "gmail": {
        "display": "Google / Gmail",
        # Label stored in ContactConnection.service for contacts linked via this plugin.
        "contact_service": "Gmail",
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "revoke_url": "https://oauth2.googleapis.com/revoke",
        "scopes": ["https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.send"],
        "client_id_env": "GOOGLE_CLIENT_ID",
        "client_secret_env": "GOOGLE_CLIENT_SECRET",
        "extra_params": {"access_type": "offline", "prompt": "consent"},
        "redirect_path": "/plugins/oauth/callback/gmail/",
        # Used to fetch a stable provider account identifier after OAuth.
        # `field` is a dot-path into the JSON response.
        "account_id_endpoint": {
            "url": "https://gmail.googleapis.com/gmail/v1/users/me/profile",
            "params": {},
            "field": "emailAddress",
        },
    },
    "google_calendar": {
        "display": "Google Calendar",
        "contact_service": None,
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "revoke_url": "https://oauth2.googleapis.com/revoke",
        "scopes": [
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/calendar.events",
        ],
        "client_id_env": "GOOGLE_CLIENT_ID",
        "client_secret_env": "GOOGLE_CLIENT_SECRET",
        "extra_params": {"access_type": "offline", "prompt": "consent"},
        "redirect_path": "/plugins/oauth/callback/google_calendar/",
    },
    "google_contacts": {
        "display": "Google Contacts",
        "contact_service": "Gmail",
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "revoke_url": "https://oauth2.googleapis.com/revoke",
        "scopes": [
            "https://www.googleapis.com/auth/contacts.readonly",
        ],
        "client_id_env": "GOOGLE_CLIENT_ID",
        "client_secret_env": "GOOGLE_CLIENT_SECRET",
        "extra_params": {"access_type": "offline", "prompt": "consent"},
        "redirect_path": "/plugins/oauth/callback/google_contacts/",
        "account_id_endpoint": {
            "url": "https://www.googleapis.com/oauth2/v2/userinfo",
            "params": {},
            "field": "email",
        },
    },
    "google_drive": {
        "display": "Google Drive",
        "contact_service": None,
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "revoke_url": "https://oauth2.googleapis.com/revoke",
        "scopes": [
            "https://www.googleapis.com/auth/drive.readonly",
        ],
        "client_id_env": "GOOGLE_CLIENT_ID",
        "client_secret_env": "GOOGLE_CLIENT_SECRET",
        "extra_params": {"access_type": "offline", "prompt": "consent"},
        "redirect_path": "/plugins/oauth/callback/google_drive/",
        "account_id_endpoint": {
            "url": "https://www.googleapis.com/drive/v3/about",
            "params": {"fields": "user(emailAddress)"},
            "field": "user.emailAddress",
        },
    },
    "outlook": {
        "display": "Outlook Mail",
        "contact_service": None,
        "auth_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "scopes": [
            "https://graph.microsoft.com/Mail.Read",
            "https://graph.microsoft.com/Mail.Send",
            "offline_access",
        ],
        "client_id_env": "MICROSOFT_CLIENT_ID",
        "client_secret_env": "MICROSOFT_CLIENT_SECRET",
        "extra_params": {},
        "redirect_path": "/plugins/oauth/callback/outlook/",
        "account_id_endpoint": {
            "url": "https://graph.microsoft.com/v1.0/me",
            "params": {},
            "field": "userPrincipalName",
        },
    },
    "notion": {
        "display": "Notion",
        "contact_service": None,
        "auth_url": "https://api.notion.com/v1/oauth/authorize",
        "token_url": "https://api.notion.com/v1/oauth/token",
        "scopes": [],  # Notion has no OAuth scopes; capabilities are set on the integration
        "client_id_env": "NOTION_CLIENT_ID",
        "client_secret_env": "NOTION_CLIENT_SECRET",
        "extra_params": {"owner": "user"},  # required by Notion authorize endpoint
        "redirect_path": "/plugins/oauth/callback/notion/",
        "token_auth_style": "basic_json",  # Notion token endpoint needs HTTP Basic auth + JSON body
        "token_never_expires": True,        # Notion tokens never expire and have no refresh_token
        "account_id_endpoint": {
            "url": "https://api.notion.com/v1/users/me",
            "params": {},
            "field": "id",  # bot user id == bot_id; stable per workspace install
            "headers": {"Notion-Version": "2022-06-28"},
        },
    },
    "outlook_calendar": {
        "display": "Outlook Calendar",
        "contact_service": None,
        "auth_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "scopes": [
            "https://graph.microsoft.com/Calendars.ReadWrite",
            "offline_access",
        ],
        "client_id_env": "MICROSOFT_CLIENT_ID",
        "client_secret_env": "MICROSOFT_CLIENT_SECRET",
        "extra_params": {},
        "redirect_path": "/plugins/oauth/callback/outlook_calendar/",
        "account_id_endpoint": {
            "url": "https://graph.microsoft.com/v1.0/me",
            "params": {},
            "field": "userPrincipalName",
        },
    },
}

# Valid ContactConnection.service values, derived from the registry.
CONTACT_SERVICES: frozenset = frozenset(
    cfg["contact_service"]
    for cfg in PLUGIN_REGISTRY.values()
    if cfg.get("contact_service")
)
