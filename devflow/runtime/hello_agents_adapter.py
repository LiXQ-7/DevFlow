"""The only production module coupled to HelloAgents; no upstream source is modified."""

import contextlib
import copy
import io
import json
import time
from dataclasses import asdict
from urllib.parse import urlparse

from hello_agents import HelloAgentsLLM, ReActAgent, ToolRegistry
from hello_agents.context.history import HistoryManager
from hello_agents.context.token_counter import TokenCounter as UpstreamTokenCounter
from hello_agents.context.truncator import ObservationTruncator
from hello_agents.core.config import Config as UpstreamConfig
from hello_agents.core.message import Message
from hello_agents.core.session_store import SessionStore
from hello_agents.tools.base import Tool
from hello_agents.tools.response import ToolResponse, ToolStatus

from .base import TurnResult, UsageSnapshot


class QuietOutput(io.TextIOBase):
    def write(self, value):
        return len(value)


def context_components(model, output_dir, max_lines, max_bytes, direction):
    return (
        UpstreamTokenCounter(model),
        ObservationTruncator(
            max_lines=max_lines,
            max_bytes=max_bytes,
            truncate_direction=direction,
            output_dir=str(output_dir),
        ),
    )


def history_round_starts(messages):
    manager = HistoryManager(min_retain_rounds=1)
    for msg in messages:
        manager.append(Message(json.dumps(msg, ensure_ascii=False), msg["role"]))
    assert manager.estimate_rounds() == sum(msg["role"] == "user" for msg in messages)
    return [i for i, msg in enumerate(manager.get_history()) if msg.role == "user"]


def count_message_payloads(counter, messages, schemas):
    encoded = [
        Message(json.dumps(message, ensure_ascii=False), message["role"]) for message in messages
    ]
    encoded.append(Message(json.dumps(list(schemas), ensure_ascii=False), "system"))
    return counter.count_messages(encoded)


def load_legacy_session(path):
    return SessionStore(session_dir=str(path.parent)).load(str(path))


class CompatibleLLM(HelloAgentsLLM):
    def invoke_with_tools(self, messages, tools, **kwargs):
        # Current DeepSeek defaults to thinking mode, whose reasoning_content protocol
        # is not retained by this upstream runtime. Explicit non-thinking mode is supported.
        if urlparse(self.base_url).hostname == "api.deepseek.com":
            kwargs.setdefault("extra_body", {"thinking": {"type": "disabled"}})
        return super().invoke_with_tools(messages, tools, **kwargs)


def make_llm(cfg):
    if not cfg.api_key.get_secret_value():
        raise ValueError("Configure DEVFLOW_API_KEY before live model evaluation")
    return CompatibleLLM(
        model=cfg.model,
        api_key=cfg.api_key.get_secret_value(),
        base_url=cfg.base_url,
        temperature=cfg.temperature,
        max_tokens=cfg.reserve_tokens,
        timeout=cfg.request_timeout,
    )


class WrappedTool(Tool):
    def __init__(self, domain):
        super().__init__(domain.name, domain.description)
        self.domain = domain

    def get_parameters(self):
        # Full Pydantic schemas are supplied directly by _build_tool_schemas.
        return []

    def run(self, parameters):
        result = self.domain.execute(parameters)
        return to_upstream_response(result)


def to_upstream_response(result):
    return ToolResponse(
        status=ToolStatus(result.status.lower()),
        text=result.model_dump_json(),
        data=result.data,
        error_info={"code": result.error_code} if result.error_code else None,
        stats=result.stats,
    )


class JournalMessages(list):
    def __init__(self, values, callback):
        super().__init__(copy.deepcopy(values))
        self.callback = callback

    def append(self, value):
        self.callback(copy.deepcopy(value))  # durable before subsequent side effects
        super().append(value)


class ModelProxy:
    def __init__(self, inner, owner):
        self.inner, self.owner, self.model = inner, owner, inner.model
        self.error = None
        self.final_received = False

    def invoke_with_tools(self, messages, tools, **kwargs):
        owner = self.owner
        started = time.perf_counter()
        try:
            prepared = owner.prepare(list(messages), tools)
            # Keep upstream's working list synchronized without generating duplicate journal events.
            messages[:] = copy.deepcopy(prepared)
            owner.messages = messages
            estimate = owner.count(prepared, tools)
            response = self.inner.invoke_with_tools(messages=prepared, tools=tools, **kwargs)
            usage = response.usage or {}
            owner.usage.requests += 1
            owner.usage.estimated_input_tokens += estimate
            owner.usage.input_tokens += usage.get("prompt_tokens", usage.get("input_tokens", 0))
            owner.usage.output_tokens += usage.get(
                "completion_tokens", usage.get("output_tokens", 0)
            )
            owner.usage.api_usage_requests += int(
                "prompt_tokens" in usage or "input_tokens" in usage
            )
            owner.event(
                "llm_request",
                {
                    "model": response.model,
                    "estimated_input_tokens": estimate,
                    "input_tokens": usage.get("prompt_tokens", usage.get("input_tokens")),
                    "output_tokens": usage.get("completion_tokens", usage.get("output_tokens")),
                    "duration_ms": (time.perf_counter() - started) * 1000,
                },
            )
            if not response.tool_calls:
                self.final_received = True
            return response
        except Exception as exc:
            self.error = exc
            owner.event(
                "error",
                {
                    "stage": "model_request",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "retryable": True,
                },
            )
            raise


class DurableReActAgent(ReActAgent):
    def _build_messages(self, input_text):
        self.owner.messages = JournalMessages(self.owner.messages, self.owner.on_message)
        return self.owner.messages

    def _build_tool_schemas(self):
        return [tool.schema() for tool in self.owner.tools]

    def _execute_tool_call(self, tool_name, arguments):
        # Pydantic validates before any conversion. Controller handles trace/context/state.
        return to_upstream_response(self.owner.execute(tool_name, arguments)).text


class HelloAgentsRuntimeAdapter:
    def __init__(
        self,
        cfg,
        tools,
        *,
        llm=None,
        prepare=None,
        on_message=None,
        execute=None,
        event=None,
        count=None,
    ):
        self.cfg, self.tools = cfg, []
        self.messages = []
        self.usage = UsageSnapshot()
        self.prepare = prepare or (lambda messages, schemas: messages)
        self.on_message = on_message or (lambda message: None)
        self.event = event or (lambda name, data: None)
        self.count = count or (lambda messages, schemas: 0)
        self.execute = execute or self._execute
        self.registry = ToolRegistry()
        self.register_tools(tools)
        if llm is None:
            if not cfg.api_key.get_secret_value():
                raise ValueError(
                    "Configure DEVFLOW_API_KEY, DEVFLOW_MODEL and DEVFLOW_BASE_URL in .env"
                )
            llm = make_llm(cfg)
        self.proxy = ModelProxy(llm, self)
        upstream_cfg = UpstreamConfig(
            trace_enabled=False,
            skills_enabled=False,
            session_enabled=False,
            subagent_enabled=False,
            todowrite_enabled=False,
            devlog_enabled=False,
            tool_output_dir=str(cfg.state_dir / "outputs"),
        )
        self.agent = DurableReActAgent(
            "DevFlow",
            self.proxy,
            tool_registry=self.registry,
            config=upstream_cfg,
            max_steps=cfg.max_steps,
        )
        self.agent.owner = self
        self.agent._builtin_tools = set()

    def _execute(self, name, args):
        from devflow.tools.base import ToolResult

        tool = next((t for t in self.tools if t.name == name), None)
        return (
            tool.execute(args) if tool else ToolResult.error("UNKNOWN_TOOL", f"Unknown tool {name}")
        )

    def register_tools(self, tools):
        self.tools = list(tools)
        with contextlib.redirect_stdout(QuietOutput()):
            for tool in tools:
                self.registry.register_tool(WrappedTool(tool))

    def run_turn(self, user_input):
        self.proxy.error, self.proxy.final_received = None, False
        before = asdict(self.usage)
        if not self.messages or self.messages[-1] != {"role": "user", "content": user_input}:
            message = {"role": "user", "content": user_input}
            self.on_message(message)
            self.messages.append(message)
        with contextlib.redirect_stdout(QuietOutput()):
            answer = self.agent.run(user_input, temperature=self.cfg.temperature)
        if self.proxy.error:
            raise self.proxy.error
        status = "completed" if self.proxy.final_received else "max_steps"
        final = {"role": "assistant", "content": answer}
        self.on_message(final)
        self.messages = list(self.messages) + [final]
        delta = UsageSnapshot(**{k: v - before[k] for k, v in asdict(self.usage).items()})
        return TurnResult(answer, status, delta)

    def get_messages(self):
        return copy.deepcopy(list(self.messages))

    def set_messages(self, messages):
        self.messages = copy.deepcopy(messages)

    def get_usage(self):
        return copy.deepcopy(self.usage)
