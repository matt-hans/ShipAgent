from copy import deepcopy

from src.registry.models import SideEffectClass, ToolContract


def to_openapi_operation(tool: ToolContract) -> dict:
    consequential = tool.side_effect in {
        SideEffectClass.write,
        SideEffectClass.purchase,
        SideEffectClass.external_mutation,
        SideEffectClass.destructive,
    }
    return {
        "operationId": tool.name,
        "summary": tool.title,
        "description": tool.description,
        "x-openai-isConsequential": consequential,
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": deepcopy(tool.input_schema)}},
        },
        "responses": {
            "200": {
                "description": "Successful response",
                "content": {
                    "application/json": {"schema": deepcopy(tool.output_schema)}
                },
            }
        },
    }
