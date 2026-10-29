import importlib
import pkgutil
from pathlib import Path

from django.apps import AppConfig


class ToolsConfig(AppConfig):
    name = "tools"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        import tools

        tools_path = str(Path(tools.__file__).parent)
        for pkg_info in pkgutil.iter_modules([tools_path]):
            if pkg_info.ispkg:
                importlib.import_module(f"tools.{pkg_info.name}")
