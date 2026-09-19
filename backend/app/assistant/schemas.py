from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator

Action = Literal[
    "create_class", "rename_class", "delete_class", "add_attribute",
    "add_method", "create_relation", "change_relation_type", "delete_relation",
]

class AssistantCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Action
    class_id: UUID | None = None
    class_name: str | None = None
    new_name: str | None = None
    attribute_name: str | None = None
    attribute_type: str | None = None
    method_name: str | None = None
    return_type: str | None = None
    source_class_id: UUID | None = None
    target_class_id: UUID | None = None
    relation_id: UUID | None = None
    relation_type: str | None = None
    requires_confirmation: bool = False

    @model_validator(mode="after")
    def validate_payload(self):
        required = {
            "create_class": ("class_name",),
            "rename_class": ("class_id", "new_name"),
            "delete_class": ("class_id",),
            "add_attribute": ("class_id", "attribute_name", "attribute_type"),
            "add_method": ("class_id", "method_name", "return_type"),
            "create_relation": ("source_class_id", "target_class_id", "relation_type"),
            "change_relation_type": ("relation_id", "relation_type"),
            "delete_relation": ("relation_id",),
        }[self.action]
        if any(getattr(self, field) in (None, "") for field in required):
            raise ValueError(f"Faltan datos para la acción {self.action}.")
        return self

class ParseRequest(BaseModel):
    diagram_id: UUID
    transcript: str = Field(min_length=1, max_length=500)

class ExecuteRequest(BaseModel):
    diagram_id: UUID
    command: AssistantCommand
    confirmed: bool = False
