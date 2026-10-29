from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.response import Response
from django.db.models import Q
from .models import Contact, ContactConnection
from .serializers import ContactSerializer, ContactConnectionSerializer
from .services import get_filtered_contacts
from plugins.plugins.registry import CONTACT_SERVICES
from backend.pagination import AivaPagination

class ContactListView(APIView):
	permission_classes = [IsAuthenticated]

	def get(self, request):
		query = request.query_params.get("search", "")
		contacts = get_filtered_contacts(request.user, query)
		paginator = AivaPagination()
		page = paginator.paginate_queryset(contacts, request)
		serializer = ContactSerializer(page, many=True)
		return paginator.get_paginated_response(serializer.data)

	def post(self, request):
		data = request.data
		contact = Contact.objects.create(
			user=request.user,
			first_name=data["first_name"],
			last_name=data.get("last_name", ""),
			alias=data.get("alias"),
			photo=data.get("photo"),
		)
		serializer = ContactSerializer(contact)
		return Response(serializer.data, status=201)


class ContactDetailView(APIView):
	permission_classes = [IsAuthenticated]

	def get(self, request, contactId):
		contact = get_object_or_404(Contact, user=request.user, id=contactId)
		serializer = ContactSerializer(contact)
		return Response(serializer.data, status=200)

	def put(self, request, contactId):
		data = request.data
		contact = get_object_or_404(Contact, user=request.user, id=contactId)
		contact.first_name = data.get("first_name", contact.first_name)
		contact.last_name = data.get("last_name", contact.last_name)
		contact.alias = data.get("alias", contact.alias)
		contact.photo = data.get("photo", contact.photo)
		contact.save()
		serializer = ContactSerializer(contact)
		return Response(serializer.data, status=200)

	def delete(self, request, contactId):
		contact = get_object_or_404(Contact, user=request.user, id=contactId)
		contact.delete()
		return Response(status=204)

class ContactConnectionListView(APIView):
	permission_classes = [IsAuthenticated]

	def get(self, request, contactId):
		contact = get_object_or_404(Contact, user=request.user, id=contactId)
		plugins = contact.connections.select_related("contact").all()
		serializer = ContactConnectionSerializer(plugins, many=True)
		return Response(serializer.data, status=200)

	def post(self, request, contactId):
		data = request.data
		contact = get_object_or_404(Contact, user=request.user, id=contactId)
		if data["service"] not in CONTACT_SERVICES:
			return Response({"error": "Plugin not available"}, status=400)
		plugin = ContactConnection.objects.create(
			contact=contact,
			service=data["service"],
			external_id=data["external_id"],
			metadata=data.get("metadata"),
		)
		serializer = ContactConnectionSerializer(plugin)
		return Response(serializer.data, status=201)

class ContactConnectionDetailView(APIView):
	permission_classes = [IsAuthenticated]

	def get(self, request, contactId, connectionId):
		contact = get_object_or_404(Contact, user=request.user, id=contactId)
		plugin = get_object_or_404(ContactConnection, contact=contact, id=connectionId)
		serializer = ContactConnectionSerializer(plugin)
		return Response(serializer.data, status=200)

	def delete(self, request, contactId, connectionId):
		contact = get_object_or_404(Contact, user=request.user, id=contactId)
		plugin = get_object_or_404(ContactConnection, contact=contact, id=connectionId)
		plugin.delete()
		return Response(status=204)

	def put(self, request, contactId, connectionId):
		data = request.data
		contact = get_object_or_404(Contact, user=request.user, id=contactId)
		plugin = get_object_or_404(ContactConnection, contact=contact, id=connectionId)
		plugin.external_id = data.get("external_id", plugin.external_id)
		plugin.metadata = data.get("metadata", plugin.metadata)
		plugin.save()
		serializer = ContactConnectionSerializer(plugin)
		return Response(serializer.data, status=200)
