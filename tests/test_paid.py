import json

import pytest

from devflow.benchmarks.paid import BudgetExceeded, BudgetLedger


def test_budget_accounts_for_concurrent_reservations(tmp_path):
    ledger = BudgetLedger(tmp_path, cap=0.01)
    key = ledger.reserve(3000, 0)
    with pytest.raises(BudgetExceeded):
        ledger.reserve(3000, 0)
    ledger.settle(key, {"prompt_tokens": 1000, "completion_tokens": 100})
    state = json.loads(ledger.path.read_text())
    assert state["estimated_spent_cny"] == pytest.approx(0.0028)
    assert state["reserved"] == {}
    assert state["requests"] == 1


def test_ambiguous_failed_call_reserves_worst_case_cost(tmp_path):
    ledger = BudgetLedger(tmp_path)
    key = ledger.reserve(1000, 1000)
    ledger.settle(key)
    state = json.loads(ledger.path.read_text())
    assert state["estimated_spent_cny"] == pytest.approx(0.01)


def test_deepseek_cached_input_billing(tmp_path):
    ledger = BudgetLedger(tmp_path)
    key = ledger.reserve(1000, 100)
    ledger.settle(
        key, {"prompt_tokens": 1000, "completion_tokens": 100, "prompt_cache_hit_tokens": 800}
    )
    state = json.loads(ledger.path.read_text())
    assert state["estimated_spent_cny"] == pytest.approx(0.001232)


def test_windows_transient_replace_conflict_is_retried(tmp_path, monkeypatch):
    ledger = BudgetLedger(tmp_path)
    original = type(ledger.path).replace
    attempts = []

    def transient(self, destination):
        attempts.append(1)
        if len(attempts) == 1:
            raise PermissionError("transient reader sharing lock")
        return original(self, destination)

    monkeypatch.setattr(type(ledger.path), "replace", transient)
    ledger.reserve(100, 100)
    assert len(attempts) == 2


def test_deepseek_non_thinking_compatibility(monkeypatch):
    from devflow.runtime.hello_agents_adapter import CompatibleLLM, HelloAgentsLLM

    observed = {}

    def capture(self, messages, tools, **kwargs):
        observed.update(kwargs)
        return "ok"

    monkeypatch.setattr(HelloAgentsLLM, "invoke_with_tools", capture)
    client = CompatibleLLM.__new__(CompatibleLLM)
    client.base_url = "https://api.deepseek.com/v1"
    assert client.invoke_with_tools([], []) == "ok"
    assert observed["extra_body"] == {"thinking": {"type": "disabled"}}


def test_context_preflight_zero_is_distinct_from_unknown_network_usage():
    from devflow.benchmarks.context_ab import request_usage

    assert request_usage([], "ContextBudgetExceeded") == (0, "no_request_context_guard")
    assert request_usage([], "ConnectionError") == ("", "unavailable")
    assert request_usage([{"input_tokens": 42}], "ContextBudgetExceeded") == (42, "api_usage")
    assert request_usage([{"input_tokens": None}], "completed") == ("", "unavailable")
