from .models import Contact, ContactConnection
from django.db.models import Q

def get_filtered_contacts(user, search_query):
    contacts = Contact.objects.filter(user=user)

    if search_query:
        search_query_lower = search_query.lower()

        exact_match_query = Q(first_name__iexact=search_query_lower) | Q(last_name__iexact=search_query_lower)
        substring_match_query = Q(first_name__icontains=search_query_lower) | Q(last_name__icontains=search_query_lower)

        exact_matches = contacts.filter(exact_match_query).order_by('first_name', 'last_name')
        if exact_matches.exists():
            return exact_matches

        return contacts.filter(substring_match_query).order_by('first_name', 'last_name')

    return contacts

def get_contact_plugin_id(contact, plugin):
    connection = ContactConnection.objects.get(contact=contact, service=plugin)
    return connection.external_id
