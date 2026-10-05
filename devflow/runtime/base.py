from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class UsageSnapshot:
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_input_tokens: int = 0
    requests: int = 0
    api_usage_requests: int = 0


@dataclass
class TurnResult:
    text: str
    status: str = "completed"
    usage: UsageSnapshot = field(default_factory=UsageSnapshot)


class AgentRuntime(Protocol):
    def run_turn(self, user_input: str) -> TurnResult: ...
    def register_tools(self, tools: list) -> None: ...
    def get_messages(self) -> list[dict]: ...
    def set_messages(self, messages: list[dict]) -> None: ...
    def get_usage(self) -> UsageSnapshot: ...
