"""Cross-process conservative spending guard for a user-authorized evaluation."""

import json
import time
from pathlib import Path
from uuid import uuid4

import httpx
from filelock import FileLock

from devflow.runtime.hello_agents_adapter import make_llm


class BudgetExceeded(RuntimeError):
    pass


class BudgetLedger:
    # DeepSeek Flash peak price, CNY / million tokens; cached inputs charged conservatively.
    input_price = 2.0
    output_price = 8.0
    cached_input_price = 0.04

    def __init__(self, directory, cap=18.0):
        self.path = Path(directory) / "budget.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(str(self.path) + ".lock", timeout=20)
        with self.lock:
            if not self.path.exists():
                self._save(
                    {
                        "cap_cny": cap,
                        "estimated_spent_cny": 0.0,
                        "reserved": {},
                        "requests": 0,
                        "input_tokens": 0,
                        "output_tokens": 0,
                    }
                )

    def _save(self, data):
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        for attempt in range(20):
            try:
                temporary.replace(self.path)
                return
            except PermissionError:
                if attempt == 19:
                    raise
                time.sleep(0.025)

    def reserve(self, input_bound, max_output):
        amount = (input_bound * self.input_price + max_output * self.output_price) / 1_000_000
        with self.lock:
            data = json.loads(self.path.read_text())
            if (
                data["estimated_spent_cny"] + sum(data["reserved"].values()) + amount
                > data["cap_cny"]
            ):
                raise BudgetExceeded("Evaluation spending limit reached")
            key = uuid4().hex
            data["reserved"][key] = amount
            self._save(data)
        return key

    def settle(self, key, usage=None):
        with self.lock:
            data = json.loads(self.path.read_text())
            reserved = data["reserved"].pop(key)
            if usage and "prompt_tokens" in usage and "completion_tokens" in usage:
                inp, out = usage["prompt_tokens"], usage["completion_tokens"]
                hit = usage.get("prompt_cache_hit_tokens", 0)
                if not isinstance(hit, int) or not 0 <= hit <= inp:
                    hit = 0
                data["estimated_spent_cny"] += (
                    (inp - hit) * self.input_price
                    + hit * self.cached_input_price
                    + out * self.output_price
                ) / 1_000_000
                data["input_tokens"] += inp
                data["output_tokens"] += out
            else:
                # An ambiguous failed request may have been charged; retain the full reservation.
                data["estimated_spent_cny"] += reserved
            data["requests"] += 1
            self._save(data)


class BudgetedLLM:
    def __init__(self, cfg, directory):
        self.inner = make_llm(cfg)
        self.model = cfg.model
        self.raw_usage = None
        # Upstream retry defaults are disabled so the ledger accounts for every paid attempt.
        client = self.inner._adapter._client or self.inner._adapter.create_client()
        self.inner._adapter._client = client.with_options(
            max_retries=0,
            http_client=httpx.Client(
                timeout=cfg.request_timeout,
                trust_env=False,
                event_hooks={"response": [self.capture_usage]},
            ),
        )
        self.ledger = BudgetLedger(directory)

    def capture_usage(self, response):
        response.read()
        if response.status_code == 200:
            try:
                self.raw_usage = response.json().get("usage")
            except ValueError:
                pass

    def invoke_with_tools(self, messages, tools, **kwargs):
        kwargs["extra_body"] = {"thinking": {"type": "disabled"}}
        maximum = kwargs.setdefault("max_tokens", 768)
        # UTF-8 byte count is a conservative token ceiling; add protocol/schema conversion margin.
        bound = (
            len(json.dumps({"messages": messages, "tools": tools}, ensure_ascii=False).encode())
            + 4096
        )
        key = self.ledger.reserve(bound, maximum)
        self.raw_usage = None
        try:
            response = self.inner.invoke_with_tools(messages=messages, tools=tools, **kwargs)
        except Exception:
            self.ledger.settle(key)
            raise
        self.ledger.settle(key, self.raw_usage or response.usage)
        return response
