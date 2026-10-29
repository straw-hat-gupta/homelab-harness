from django.http import JsonResponse
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated

from plugins.models import Credentials
from tools.registry import get_schemas_for_planner


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def tools_view(request):
    """Return tool schemas the user can actually use.

    Only tools whose plugin the user has an active credential for are returned,
    plus system tools (no plugin required). Optional query param:
      ?plugin=<plugin_id>  — further filter to one plugin's tools
                             (pass "system" to get only system tools)
    """
    connected_plugins = frozenset(
        Credentials.objects.filter(user=request.user, status="active")
        .values_list("plugin", flat=True)
    )
    schemas = get_schemas_for_planner(enabled_plugins=connected_plugins)

    plugin_filter = request.query_params.get("plugin")
    if plugin_filter:
        if plugin_filter == "system":
            schemas = [s for s in schemas if not s.get("plugin_id")]
        else:
            schemas = [s for s in schemas if s.get("plugin_id") == plugin_filter]

    return JsonResponse({"tools": schemas})
