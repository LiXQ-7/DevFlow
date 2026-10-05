"""Validated domain contract, independent from the external runtime."""

from abc import ABC, abstractmethod
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class Args(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ToolResult(BaseModel):
    status: Literal["SUCCESS", "PARTIAL", "ERROR"] = "SUCCESS"
    text: str = ""
    data: dict = Field(default_factory=dict)
    error_code: str | None = None
    stats: dict = Field(default_factory=dict)
    context: dict = Field(default_factory=dict)

    @classmethod
    def error(cls, code, text, **data):
        return cls(status="ERROR", text=text, error_code=code, data=data)


class ToolFailure(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class BaseCodingTool(ABC):
    name: str
    description: str
    args_schema: type[Args]

    def __init__(self, root, output_dir):
        self.root = root.resolve()
        self.output_dir = output_dir

    def schema(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.args_schema.model_json_schema(),
            },
        }

    def execute(self, arguments) -> ToolResult:
        started = perf_counter()
        try:
            result = self.run(self.args_schema.model_validate(arguments))
        except ValidationError as exc:
            result = ToolResult.error("INVALID_PARAM", str(exc.errors(include_input=False)))
        except ToolFailure as exc:
            result = ToolResult.error(exc.code, str(exc))
        except FileNotFoundError:
            result = ToolResult.error("NOT_FOUND", "File or directory does not exist")
        except PermissionError:
            result = ToolResult.error("PERMISSION", "Access denied")
        except UnicodeError:
            result = ToolResult.error("INVALID_ENCODING", "Expected UTF-8 text")
        except (OSError, ValueError) as exc:
            result = ToolResult.error("EXECUTION_ERROR", str(exc))
        result.stats["duration_ms"] = round((perf_counter() - started) * 1000, 3)
        return result

    @abstractmethod
    def run(self, args: Args) -> ToolResult: ...
