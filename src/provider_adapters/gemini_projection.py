from copy import deepcopy

from src.registry.models import ToolContract


def to_gemini_function(tool: ToolContract) -> dict:
    return {
        "name": tool.name,
        "description": tool.description,
        "parameters": deepcopy(tool.input_schema),
    }
