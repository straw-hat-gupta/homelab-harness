from rest_framework import serializers
from .models import Task, SubTask


class SubTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubTask
        fields = ('id', 'task', 'action', 'detail', 'plugin', 'recipients', 'order', 'created_at')
        read_only_fields = ('id', 'task', 'created_at')
        extra_kwargs = {
            'detail': {'required': False, 'default': ''},
            'recipients': {'required': False, 'default': list},
        }


class TaskSerializer(serializers.ModelSerializer):
    sub_tasks = SubTaskSerializer(many=True, read_only=True)

    class Meta:
        model = Task
        fields = ('id', 'project', 'title', 'description', 'status', 'sub_tasks', 'created_at', 'updated_at')
        read_only_fields = ('id', 'project', 'created_at', 'updated_at')
