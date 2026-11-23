# Reproduce the AgentHub animated demo

The [README animation](media/agenthub-workflow.gif) records the repository's actual Vue frontend with Playwright. A small, in-memory server supplies scripted REST responses and SSE events so the walkthrough can be reproduced without a model key, backend, MySQL or Docker.

## Walkthrough

1. Browse three agents: Orchestrator, Data Analyst and Report Builder.
2. Submit a request containing fictional spending figures: Travel $180, Meals $60 and Software $60.
3. Follow a streamed coordinator response and two specialist responses in one conversation.
4. Expand the proposed file contents and click the real **Approve (Y)** control. The decision reaches the local fixture endpoint and the approval card updates.
5. Inspect the workflow, open the Files panel and preview the $300 summary in the application's sandboxed HTML iframe.

This is a **scripted UI demonstration**. Agent messages, tool events and the HTML report are predetermined fixture data. Approval makes the synthetic report available in memory; no file-write tool or model executes. The animation's frame timing is edited for readability and is not a latency benchmark. The original application's components and iframe sandbox remain unchanged.

## Record locally

Use Node.js 22.12+ and Python 3.11+. Run these commands from the repository root.

```bash
cd frontend
npm ci --ignore-scripts
cd ..
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r docs/demo/requirements.txt
python -m playwright install chromium
python docs/demo/capture.py
```

On Linux, Playwright may also require browser system dependencies; its installer reports any missing packages. To use an existing Chrome or Chromium installation instead of downloading a browser:

```bash
python docs/demo/capture.py --browser '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
```

The script starts Vite and the fixture on temporary loopback ports, captures the walkthrough, and stops both servers. A temporary Vite configuration redirects API requests to the fixture and ignores frontend `.env` files. The demo uses a placeholder login token only in the local browser session; it needs no real account or credentials. Google Fonts CSS is replaced locally with an empty stylesheet, using system fonts. Other non-local browser requests cause the capture to fail.

To write assets somewhere else:

```bash
python docs/demo/capture.py --output /tmp/agenthub-demo
```

## Files and checks

| File | Purpose |
| --- | --- |
| [demo/capture.py](demo/capture.py) | Start the local services, interact with the real UI and encode the GIF |
| [demo/fixture_server.py](demo/fixture_server.py) | In-memory agents, conversation, scripted SSE events, approval and report |
| [media/agenthub-workflow.gif](media/agenthub-workflow.gif) | Looping 1200 × 870 walkthrough with visible scripted-demo labels |
| [media/agenthub-approval.png](media/agenthub-approval.png) | Full-size pending approval screenshot |
| [media/agenthub-report.png](media/agenthub-report.png) | Full-size HTML report preview screenshot |
| [media/capture-checks.json](media/capture-checks.json) | Capture assertions and observed local API routes |

The recorder asserts that the chat request and approval reach the fixture, the streamed conversation renders, the report preview contains **$300**, and no browser errors, unknown fixture routes or unexpected external requests occur. It verifies the generated GIF has multiple frames and loops. A failed capture saves `capture-failure.png` for local debugging.

These checks cover the demonstrated frontend interactions. They do not validate production orchestration, model quality, authentication or approval-policy enforcement. Rendering and fonts can vary slightly across browser versions and operating systems.
