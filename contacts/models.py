from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()

class Contact(models.Model):
	user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="contacts")
	alias = models.CharField(max_length=255, null=True, blank=True)
	first_name = models.CharField(max_length=255)
	last_name = models.CharField(max_length=255, null=True, blank=True)
	photo = models.ImageField(upload_to="contact_photos/", null=True, blank=True)
	created_at = models.DateTimeField(auto_now_add=True)

	class Meta:
		db_table = "Contacts"

	def __str__(self):
		return f"{self.first_name} {self.last_name}"


class ContactConnection(models.Model):
	contact = models.ForeignKey(Contact, on_delete=models.CASCADE, related_name="connections")
	service = models.CharField(max_length=255)
	alias = models.CharField(max_length=255, null=True, blank=True)
	external_id = models.CharField(max_length=255)
	metadata = models.JSONField(null=True, blank=True)

	class Meta:
		db_table = "ContactConnections"
		unique_together = ('contact', 'service', 'external_id')

	def __str__(self):
		return f"{self.contact.first_name} {self.contact.last_name} — {self.service}"
