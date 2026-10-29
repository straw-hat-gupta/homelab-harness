from rest_framework import serializers
from .models import Contact, ContactConnection

class ContactSerializer(serializers.ModelSerializer):
	class Meta:
		model = Contact
		fields = ['user', 'id', 'alias', 'first_name', 'last_name', 'photo', 'created_at']
		extra_kwargs = {
			'user': {'read_only': True},
			'created_at': {'read_only': True},
			'alias': {'required': False},
			'last_name': {'required': False},
			'photo': {'required': False}
		}

class ContactConnectionSerializer(serializers.ModelSerializer):
	class Meta:
		model = ContactConnection
		fields = ['contact', 'service', 'alias', 'external_id', 'metadata']
