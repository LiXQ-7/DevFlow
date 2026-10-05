"""Inspect the installed runtime; deterministic LLM exercises the actual upstream loop."""

import inspect
import json
import tempfile
from importlib.metadata import version
from pathlib import Path

from hello_agents import HelloAgentsLLM, ReActAgent, ToolRegistry
from hello_agents.context.history import HistoryManager
from hello_agents.context.token_counter import TokenCounter
from hello_agents.context.truncator import ObservationTruncator
from hello_agents.core.config import Config
from hello_agents.core.llm_response import LLMToolResponse, ToolCall
from hello_agents.core.session_store import SessionStore
from hello_agents.tools.base import Tool
from hello_agents.tools.builtin import ReadTool
from hello_agents.tools.response import ToolResponse


def main():
    result = {"version": version("hello-agents"), "signatures": {}}
    for obj in (
        ReActAgent,
        HelloAgentsLLM,
        ToolRegistry.register_tool,
        Tool,
        ToolResponse,
        HistoryManager,
        TokenCounter,
        ObservationTruncator,
        SessionStore,
        SessionStore.save,
        SessionStore.load,
    ):
        result["signatures"][obj.__qualname__] = str(inspect.signature(obj))
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "probe.txt"
        path.write_text("devflow-probe-ok", encoding="utf-8")

        class FakeLLM:
            model = "gpt-4"
            calls = 0

            def invoke_with_tools(self, messages, tools, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return LLMToolResponse(
                        None,
                        [ToolCall("probe", "Read", json.dumps({"path": str(path)}))],
                        self.model,
                    )
                assert "devflow-probe-ok" in messages[-1]["content"]
                return LLMToolResponse("probe passed", [], self.model)

        registry = ToolRegistry()
        registry.register_tool(ReadTool())
        cfg = Config(
            trace_enabled=False,
            session_enabled=False,
            skills_enabled=False,
            subagent_enabled=False,
            todowrite_enabled=False,
            devlog_enabled=False,
            tool_output_dir=str(Path(temp) / "output"),
        )

        class ProbeAgent(ReActAgent):
            def _execute_tool_call(self, tool_name, arguments):
                return self.tool_registry.execute_tool(tool_name, arguments).to_json()

        agent = ProbeAgent("probe", FakeLLM(), registry, config=cfg)
        assert agent.run("Read probe.txt") == "probe passed"
    result["function_calling_probe"] = "PASS (scripted LLM, real upstream ReActAgent and ReadTool)"
    target = Path("docs/runtime-probe.json")
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
