from django.urls import path
from contacts.views import ContactListView, ContactDetailView, ContactConnectionListView, ContactConnectionDetailView

urlpatterns = [
	# Contacts
	path('', ContactListView.as_view(), name='contact-list'),
	path('<int:contactId>/', ContactDetailView.as_view(), name='contact-detail'),

	# Contact Connections
	path('<int:contactId>/connections/', ContactConnectionListView.as_view(), name='contact-connection-list'),
	path('<int:contactId>/connections/<int:connectionId>/', ContactConnectionDetailView.as_view(), name='contact-connection-detail'),
]