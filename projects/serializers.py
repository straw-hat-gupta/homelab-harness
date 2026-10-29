from rest_framework import serializers
from .models import Projects

class ProjectsSerializer(serializers.ModelSerializer):
	class Meta:
		model = Projects
		fields = ['user', 'id', 'name', 'description', 'system_prompt', 'plugins', 'active_context_from', 'created_at']
		extra_kwargs = {
			'user': {'read_only': True},
			'created_at': {'read_only': True},
			'active_context_from': {'required': False},
			'description': {'required': False},
			'system_prompt': {'required': False},
			'plugins': {'required': False},
			'updated_at': {'read_only': True},
		}
