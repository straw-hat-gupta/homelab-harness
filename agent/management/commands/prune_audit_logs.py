"""Management command: prune_audit_logs

Deletes AgentAction and PlannerUsage rows older than --days (default 90).
Safe to run via cron or Celery Beat: manage.py prune_audit_logs
"""
import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Delete AgentAction and PlannerUsage rows older than the retention window."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=90,
            help="Delete records older than this many days (default: 90).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print counts that would be deleted without deleting.",
        )

    def handle(self, *args, **options):
        from agent.models import AgentAction, PlannerUsage

        days = options["days"]
        cutoff = timezone.now() - datetime.timedelta(days=days)

        action_qs = AgentAction.objects.filter(timestamp__lt=cutoff)
        usage_qs = PlannerUsage.objects.filter(timestamp__lt=cutoff)

        if options["dry_run"]:
            self.stdout.write(
                f"[dry-run] {action_qs.count()} AgentAction and "
                f"{usage_qs.count()} PlannerUsage rows older than {days} days would be deleted."
            )
            return

        deleted_actions, _ = action_qs.delete()
        deleted_usage, _ = usage_qs.delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {deleted_actions} AgentAction and {deleted_usage} PlannerUsage rows older than {days} days."
            )
        )
