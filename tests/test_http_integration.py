"""Exercise real OpenAI-compatible HTTP serialization, SDK and upstream loop, without paid API calls."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pydantic import SecretStr

from devflow.controller import DevFlowController


def test_openai_compatible_http_roundtrip(cfg):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(request)
            message = {"role": "assistant", "content": "HTTP integration passed"}
            if len(requests) == 1:
                message = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "http-call",
                            "type": "function",
                            "function": {
                                "name": "Write",
                                "arguments": json.dumps(
                                    {"path": "http.txt", "content": "from HTTP"}
                                ),
                            },
                        }
                    ],
                }
            raw = json.dumps(
                {
                    "id": "chatcmpl-test",
                    "object": "chat.completion",
                    "created": 1,
                    "model": "local-test",
                    "choices": [
                        {
                            "index": 0,
                            "message": message,
                            "finish_reason": "tool_calls" if len(requests) == 1 else "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 42, "completion_tokens": 7, "total_tokens": 49},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    cfg.base_url = f"http://127.0.0.1:{server.server_port}/v1"
    cfg.api_key = SecretStr("test-not-a-real-key")
    try:
        controller = DevFlowController(cfg, new=True)
        result = controller.run_turn("write http.txt")
        assert result.text == "HTTP integration passed"
        assert result.usage.input_tokens == 84 and result.usage.output_tokens == 14
        assert requests[1]["messages"][-1]["tool_call_id"] == "http-call"
        assert (cfg.project_root / "http.txt").read_text() == "from HTTP"
        assert len(requests[0]["tools"]) == 6
        assert "test-not-a-real-key" not in controller.trace.path.read_text(encoding="utf-8")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
