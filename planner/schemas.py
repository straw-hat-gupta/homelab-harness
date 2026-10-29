from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    id: str = Field(..., description="Unique step identifier, e.g. 'step_1'")
    tool: str = Field(..., description="Tool name from the registry")
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Parameters for the tool. "
            "Use '$output_var' to reference a prior step's result. "
            "Use '$input.<name>' to reference a workflow run-time input."
        ),
    )
    output_var: str = Field(..., description="Variable name to store this step's result in")
    account_id: Optional[str] = Field(
        default=None,
        description=(
            "Account identifier to use when the user has multiple accounts connected "
            "for this step's plugin (e.g. 'user@gmail.com'). Omit when only one account exists."
        ),
    )


class Plan(BaseModel):
    steps: List[PlanStep] = Field(..., description="Ordered list of steps to execute")
    final_output_var: str = Field(
        ..., description="The output_var whose value is returned as the final answer"
    )
    summary: str = Field(
        ...,
        description=(
            "One or two sentences describing exactly what this plan will do, written as "
            "'I will...'. Must name key specifics: email recipients, subjects, cities, "
            "data being used, etc. This is shown to the user before execution."
        ),
    )
