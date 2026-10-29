"""
Management command: purge_planner_usage

Deletes PlannerUsage rows older than PLANNER_USAGE_RETENTION_DAYS (default 90).
Run via Celery Beat or cron: manage.py purge_planner_usage
"""
from django.core.management.base import BaseCommand
from django.conf import settings
from django.utils import timezone
import datetime


class Command(BaseCommand):
    help = "Delete PlannerUsage rows older than the retention window."

    def add_arguments(self, parser):
        """Register command-line arguments.

        Args:
            parser: Django management command argument parser.

        Returns:
            None.
        """
        parser.add_argument(
            "--days",
            type=int,
            default=None,
            help="Override retention days (default: PLANNER_USAGE_RETENTION_DAYS setting or 90).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the count of rows that would be deleted without deleting them.",
        )

    def handle(self, *args, **options):
        """Delete planner usage rows older than the retention window.

        Args:
            *args: Positional command arguments.
            **options: Parsed command options.

        Returns:
            None.
        """
        from agent.models import PlannerUsage

        days = options["days"] or getattr(settings, "PLANNER_USAGE_RETENTION_DAYS", 90)
        cutoff = timezone.now() - datetime.timedelta(days=days)
        qs = PlannerUsage.objects.filter(timestamp__lt=cutoff)

        if options["dry_run"]:
            self.stdout.write(f"[dry-run] {qs.count()} rows older than {days} days would be deleted.")
            return

        deleted, _ = qs.delete()
        self.stdout.write(self.style.SUCCESS(f"Deleted {deleted} PlannerUsage rows older than {days} days."))
