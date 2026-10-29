class PluginNotConnectedError(Exception):
    def __init__(self, plugin_id: str) -> None:
        self.plugin_id = plugin_id
        super().__init__(f"Plugin '{plugin_id}' is not connected. Please connect it in Settings.")


class ToolExecutionError(Exception):
    def __init__(self, step_id: str, tool: str, message: str, completed_steps: list[dict] | None = None) -> None:
        self.step_id = step_id
        self.tool = tool
        self.completed_steps = completed_steps or []
        super().__init__(message)
