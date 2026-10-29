from django.contrib import admin

from .models import AgentAction, PlannerUsage, UserMemory


@admin.register(AgentAction)
class AgentActionAdmin(admin.ModelAdmin):
    list_display = ("user", "tool", "status", "timestamp")
    list_filter = ("status", "tool")
    ordering = ("-timestamp",)
    readonly_fields = ("user", "tool", "params_summary", "status", "timestamp")
    search_fields = ("user__email", "tool")


@admin.register(PlannerUsage)
class PlannerUsageAdmin(admin.ModelAdmin):
    list_display = ("user", "model", "call_type", "input_tokens", "output_tokens", "timestamp")
    ordering = ("-timestamp",)
    readonly_fields = ("user", "model", "call_type", "input_tokens", "output_tokens", "timestamp")
    search_fields = ("user__email",)


@admin.register(UserMemory)
class UserMemoryAdmin(admin.ModelAdmin):
    list_display = ("user", "key", "source", "updated_at")
    list_filter = ("source",)
    ordering = ("-updated_at",)
    readonly_fields = ("user", "source", "created_at", "updated_at")
    search_fields = ("user__email", "key")


