"""In-memory REST/SSE fixtures for recording AgentHub's actual Vue UI.

No model, database, shell tool, enterprise service, or file-write tool is run.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import queue
import threading
from urllib.parse import parse_qs, urlparse


STAMP = "2026-11-23T04:00:00Z"
CONVERSATION = "portfolio-demo"
FILE_NAME = "spending-summary.html"
REPORT = """<!doctype html><html lang="en"><meta charset="utf-8">
<title>Demo spending summary</title><style>
body{font:16px/1.65 system-ui,sans-serif;background:#f5f3ff;color:#25213f;padding:30px}
main{max-width:660px;margin:auto;background:white;padding:36px;border-radius:20px}
small{color:#71618e}h1{font-size:30px;margin:14px 0}strong{font-size:48px;color:#6757ca}
.row{display:flex;justify-content:space-between;margin-top:20px}.bar{height:9px;background:#eeeaf8;border-radius:8px}
.bar i{display:block;height:100%;background:#9580e0;border-radius:8px}footer{font-size:12px;color:#797083;margin-top:30px}
</style><main><small>AGENTHUB / FICTIONAL DEMO DATA</small>
<h1>Spending, made clear.</h1><strong>$300</strong><p>Total across three demo categories.</p>
<div class="row"><span>Travel</span><b>$180 · 60%</b></div><div class="bar"><i style="width:60%"></i></div>
<div class="row"><span>Meals</span><b>$60 · 20%</b></div><div class="bar"><i style="width:20%"></i></div>
<div class="row"><span>Software</span><b>$60 · 20%</b></div><div class="bar"><i style="width:20%"></i></div>
<footer>Prepared by the recording fixture. No live model or financial system was called.</footer></main></html>"""


def agent(identifier, name, kind, description):
    return {"id": identifier, "user_id": "demo-user", "name": name, "type": kind,
            "description": description, "system_prompt": "Fictional recording fixture.",
            "capabilities": {"supports_code": True, "supports_diff": True,
                             "supports_approval": True, "supports_image": False},
            "tags": ["demo"], "is_public": False, "is_active": True,
            "skill_ids": [], "mcp_server_ids": [], "created_at": STAMP, "updated_at": STAMP}


AGENTS = [
    agent("orchestrator", "Orchestrator", "claude", "Break down the request and coordinate the specialists."),
    agent("data-analyst", "Data Analyst", "codex", "Check the demo figures and explain category totals."),
    agent("report-builder", "Report Builder", "claude", "Prepare a report and request approval before writing."),
]


class Fixture:
    def __init__(self):
        self.events = queue.Queue()
        self.connected = threading.Event()
        self.submitted = threading.Event()
        self.approved = threading.Event()
        self.closed = threading.Event()
        self.requests = []
        self.unhandled = []
        self.messages = []
        self.workflows = []
        self.file_ready = False
        self.prompt = ""

    def conversation(self):
        return {"id": CONVERSATION, "user_id": "demo-user", "title": "Spending summary · Demo",
                "mode": "group", "is_pinned": True, "is_archived": False,
                "last_message_preview": "Three specialists, one shared workspace.",
                "last_message_at": STAMP, "message_count": len(self.messages), "unread_count": 0,
                "agents": AGENTS, "created_at": STAMP, "updated_at": STAMP}

    def emit(self, event_type, **values):
        self.events.put({"type": event_type, "timestamp": STAMP, **values})

    def start(self, agent_id, suffix=""):
        selected = next(a for a in AGENTS if a["id"] == agent_id)
        identity = {"agent_id": agent_id, "thread_id": "thread-" + agent_id + suffix,
                    "message_id": "message-" + agent_id + suffix}
        self.emit("agent_start", **identity, agent_name=selected["name"])
        return identity

    def block(self, identity, block):
        self.emit("block_start", **identity, block=block)

    def text(self, identity, content, identifier="text"):
        block_id = identity["message_id"] + "-" + identifier
        self.block(identity, {"block_id": block_id, "type": "text", "content": content})
        self.emit("block_stop", **identity, block_id=block_id, final_fields={"content": content})

    def done(self, identity):
        self.emit("agent_done", **identity)

    def propose(self):
        message = {"id": "approval-message", "conversation_id": CONVERSATION,
                   "agent_id": "report-builder", "sender": "Report Builder", "role": "assistant",
                   "status": "done", "is_deleted": False, "created_at": STAMP,
                   "blocks": [{"block_id": "write-report", "type": "approval", "action": "create_file",
                               "detail": json.dumps({"path": FILE_NAME, "content": REPORT}), "status": "pending"}]}
        self.messages.append(message)
        self.emit("message_appended", conversation_id=CONVERSATION, message=message)

    def handler(self):
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def json(self, data, status=200):
                body = json.dumps({"code": status, "message": "local demo fixture", "data": data}).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                path = urlparse(self.path).path
                fixture.requests.append(["GET", path])
                if path.startswith("/api/v1/chat/stream/"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    self.wfile.write(b": local demo connected\n\n")
                    self.wfile.flush()
                    fixture.connected.set()
                    try:
                        while not fixture.closed.is_set():
                            try:
                                event = fixture.events.get(timeout=1)
                            except queue.Empty:
                                continue
                            self.wfile.write(("event: " + event["type"] + "\ndata: " + json.dumps(event) + "\n\n").encode())
                            self.wfile.flush()
                            if event["type"] == "queue_drained":
                                return
                    except (BrokenPipeError, ConnectionResetError):
                        return
                elif path == "/api/v1/agents":
                    self.json(AGENTS)
                elif path.startswith("/api/v1/agents/"):
                    self.json(next((a for a in AGENTS if a["id"] == path.rsplit("/", 1)[-1]), AGENTS[0]))
                elif path == "/api/v1/conversations":
                    self.json([fixture.conversation()])
                elif path == "/api/v1/conversations/" + CONVERSATION:
                    self.json(fixture.conversation())
                elif path.endswith("/messages"):
                    self.json([] if "before" in parse_qs(urlparse(self.path).query) else fixture.messages)
                elif path.endswith("/token_usage"):
                    self.json({"conversation_id": CONVERSATION, "by_agent": [],
                               "total": {"tokens_input": 0, "tokens_output": 0}})
                elif path == "/api/v1/workflows":
                    self.json(fixture.workflows)
                elif path in ("/api/v1/skills", "/api/v1/squads", "/api/v1/mcp-servers", "/api/v1/mcp_servers"):
                    self.json([])
                elif path.endswith("/files/raw"):
                    if fixture.file_ready:
                        self.json({"content": REPORT, "mime_type": "text/html", "size": len(REPORT.encode())})
                    else:
                        self.json({"error": "Demo report is not available yet"}, 404)
                elif path.endswith("/files"):
                    self.json({"files": [{"name": FILE_NAME, "path": FILE_NAME, "size": len(REPORT.encode()),
                                          "mtime": 1795406400, "is_dir": False}] if fixture.file_ready else []})
                else:
                    fixture.unhandled.append(["GET", path])
                    self.json({"error": "Unimplemented demo route"}, 404)

            def do_POST(self):
                path = urlparse(self.path).path
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                fixture.requests.append(["POST", path])
                if path == "/api/v1/chat":
                    fixture.prompt = body["content"]
                    fixture.submitted.set()
                    self.json({"user_message_id": "user-request", "conversation_id": CONVERSATION, "status": "processing"})
                elif path == "/api/v1/approvals/write-report/decide":
                    if body.get("decision") != "approve":
                        self.json({"error": "This recording exercises approval"}, 400)
                        return
                    fixture.approved.set()
                    for message in fixture.messages:
                        for block in message["blocks"]:
                            if block["block_id"] == "write-report":
                                block["status"] = "approved"
                    self.json({"status": "approved"})
                elif path == "/api/v1/workflows":
                    row = {"id": "demo-workflow", "user_id": "demo-user", "created_at": STAMP, **body}
                    fixture.workflows.append(row)
                    self.json(row)
                else:
                    fixture.unhandled.append(["POST", path])
                    self.json({"error": "Unimplemented demo route"}, 404)

        return Handler

    def serve(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), self.handler())
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server
