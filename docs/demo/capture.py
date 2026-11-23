"""Record the real Vue UI using a local REST/SSE fixture, without a model key."""
import argparse
from contextlib import contextmanager
from io import BytesIO
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import time
from urllib.parse import urlparse
from urllib.request import urlopen

from PIL import Image, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright

from fixture_server import Fixture, CONVERSATION, FILE_NAME, REPORT


ROOT = Path(__file__).resolve().parents[2]


def font(size):
    for name in ("/System/Library/Fonts/Supplemental/Arial.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if Path(name).exists():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default(size=size)


class Recorder:
    def __init__(self, page):
        self.page, self.frames, self.durations = page, [], []

    def snap(self, step, duration=1600):
        self.page.wait_for_timeout(180)
        shot = Image.open(BytesIO(self.page.screenshot(animations="disabled"))).convert("RGB")
        # Capture at 2x density and preserve twice the original GIF resolution.
        # All page coordinates, framing, caption proportions and timings stay fixed.
        shot = shot.resize((2400, 1500), Image.Resampling.LANCZOS)
        frame = Image.new("RGB", (2400, 1740), "#13182b")
        frame.paste(shot, (0, 168))
        draw = ImageDraw.Draw(frame)
        draw.text((50, 22), "AgentHub / Multi-agent workspace", fill="#f6f5ff", font=font(52))
        draw.text((52, 96), step, fill="#aba5ff", font=font(38))
        draw.rounded_rectangle((1802, 40, 2354, 110), radius=16, fill="#2a3050")
        draw.text((1828, 58), "VUE UI / SCRIPTED DEMO", fill="#e2e4f4", font=font(34))
        draw.text((52, 1690), "Fictional data + local REST/SSE fixtures. No live model, enterprise system, or deployment.",
                  fill="#aeb9d4", font=font(30))
        self.frames.append(frame)
        self.durations.append(duration)

    def save(self, output):
        # A shared palette avoids distracting color flicker between frames.
        sample = Image.new("RGB", (600 * 4, 436 * ((len(self.frames) + 3) // 4)))
        for i, frame in enumerate(self.frames):
            sample.paste(frame.resize((600, 436)), ((i % 4) * 600, (i // 4) * 436))
        palette = sample.quantize(colors=256)
        frames = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in self.frames]
        output.mkdir(parents=True, exist_ok=True)
        target = output / "agenthub-workflow.gif"
        frames[0].save(target, save_all=True, append_images=frames[1:], duration=self.durations,
                       loop=0, optimize=True, disposal=2)
        with Image.open(target) as check:
            assert check.n_frames > 5 and check.info["loop"] == 0
            print(json.dumps({"asset": str(target), "frames": check.n_frames,
                              "duration_ms": sum(self.durations), "bytes": target.stat().st_size}))


@contextmanager
def frontend(fixture_url):
    directory = ROOT / "frontend"
    vite = directory / "node_modules/vite/bin/vite.js"
    if not vite.exists():
        raise SystemExit("Install frontend dependencies first: cd frontend && npm ci")
    with socket.socket() as port_socket:
        port_socket.bind(("127.0.0.1", 0))
        port = port_socket.getsockname()[1]
    # The temporary config overrides every production proxy and ignores .env files.
    # Application components and the checked-in Vite config are never edited.
    with tempfile.TemporaryDirectory(prefix="agenthub-demo-") as temporary:
        with tempfile.NamedTemporaryFile(mode="w", prefix=".capture-", suffix=".mjs",
                                         dir=directory, delete=False) as config:
            config.write("import original from './vite.config.ts';\nexport default {...original, "
                         + "envDir: " + json.dumps(temporary) + ", server: {host: '127.0.0.1', hmr: false, strictPort: true, port: "
                         + str(port) + ", proxy: {'/api': " + json.dumps(fixture_url) + "}}};\n")
        log_path = Path(temporary) / "vite.log"
        try:
            with log_path.open("w") as log:
                process = subprocess.Popen(["node", str(vite), "--config", config.name], cwd=directory,
                                           stdout=log, stderr=subprocess.STDOUT)
                try:
                    url = f"http://127.0.0.1:{port}"
                    for _ in range(120):
                        if process.poll() is not None:
                            raise RuntimeError(log_path.read_text())
                        try:
                            with urlopen(url, timeout=1):
                                break
                        except OSError:
                            time.sleep(.25)
                    else:
                        raise RuntimeError("Vite did not start: " + log_path.read_text())
                    yield url
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=8)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
        finally:
            Path(config.name).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", help="Optional Chrome/Chromium executable")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/media")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    fixture = Fixture()
    server = fixture.serve()
    errors, blocked, offline_fonts = [], [], []
    try:
        with frontend(f"http://127.0.0.1:{server.server_port}") as url, sync_playwright() as playwright:
            # Native density also keeps sandboxed iframe text sharp in Chrome.
            browser = playwright.chromium.launch(headless=True, executable_path=args.browser,
                                                 args=["--force-device-scale-factor=2"])
            context = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2,
                                          locale="en-US", timezone_id="UTC")
            context.add_init_script("""if (window.top === window) { localStorage.setItem('agenthub-lang', 'en');
                localStorage.setItem('agenthub-accent', 'violet');
                localStorage.setItem('agenthub-tokens', 'false');
                localStorage.setItem('auth.access_token', 'local-demo-not-a-real-token');
                localStorage.setItem('auth.user', JSON.stringify({id:'demo-user', username:'Portfolio Demo', display_name:'Portfolio Demo'})); }""")

            def local_only(route):
                host = urlparse(route.request.url).hostname
                if host == "fonts.googleapis.com":
                    offline_fonts.append(route.request.url)
                    route.fulfill(status=200, content_type="text/css", body="/* Offline capture: use system font fallback. */")
                elif host in ("127.0.0.1", "localhost") or route.request.url.startswith(("data:", "blob:")):
                    route.continue_()
                else:
                    blocked.append(route.request.url)
                    route.abort()

            context.route("**/*", local_only)
            context.route_web_socket("**/api/v1/ws/**", lambda socket: socket.on_message(lambda _: None))
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
            page.clock.set_fixed_time("2026-11-23T04:00:00Z")
            recorder = Recorder(page)
            try:
                page.goto(url + "/agents", wait_until="networkidle")
                page.get_by_text("Report Builder", exact=True).first.wait_for()
                recorder.snap("01 / Choose specialists with complementary roles", 2200)
                page.goto(url + "/chat/" + CONVERSATION, wait_until="domcontentloaded")
                editor = page.locator('[contenteditable="true"]').first
                editor.wait_for()
                # Keep pumping Playwright's routing callbacks while waiting for SSE.
                for _ in range(100):
                    if fixture.connected.is_set():
                        break
                    page.wait_for_timeout(50)
                assert fixture.connected.is_set(), "SSE connection was not established"
                prompt = "Use the demo figures: Travel $180, Meals $60, Software $60. Build a spending summary and ask before writing the report."
                for length in (30, 65, len(prompt)):
                    editor.fill(prompt[:length])
                    recorder.snap("02 / One request, shared by the whole team", 240)
                recorder.snap("02 / One request, shared by the whole team", 2000)
                editor.press("Enter")
                page.wait_for_timeout(350)
                assert fixture.submitted.is_set(), "The UI did not submit the request"

                lead = fixture.start("orchestrator")
                fixture.block(lead, {"block_id": "lead-text", "type": "text", "content": ""})
                for chunk in ("I'll coordinate the analysis and report. ", "The Data Analyst will verify the totals; ",
                              "the Report Builder will prepare an approval request."):
                    fixture.emit("block_delta", **lead, block_id="lead-text", delta={"content": chunk})
                    recorder.snap("03 / Watch the coordinator organize the task", 380)
                fixture.emit("block_stop", **lead, block_id="lead-text")
                fixture.block(lead, {"block_id": "dispatch", "type": "tool_use", "tool_name": "dispatch_agent",
                                     "input": {"agents": ["data-analyst", "report-builder"]},
                                     "output": "Two specialists assigned (scripted fixture).", "status": "completed"})
                fixture.done(lead)
                analyst = fixture.start("data-analyst")
                builder = fixture.start("report-builder")
                fixture.text(analyst, "Checking the three supplied categories and their shares of the total...")
                fixture.text(builder, "Preparing a compact HTML report. File creation will wait for your approval.")
                page.get_by_text("Checking the three supplied", exact=False).first.wait_for()
                recorder.snap("03 / Follow two specialists working in the same conversation", 2300)
                fixture.text(analyst, "Verified demo total: **$300**. Travel is **60%**; Meals and Software are **20%** each.", "totals")
                fixture.done(analyst)
                fixture.done(builder)
                fixture.propose()
                approve = page.get_by_role("button", name="Approve (Y)", exact=True)
                approve.wait_for()
                approve.scroll_into_view_if_needed()
                assert not fixture.approved.is_set() and not fixture.file_ready
                recorder.snap("04 / Inspect the proposed file before approving the operation", 2600)
                page.screenshot(path=str(args.output / "agenthub-approval.png"))
                page.get_by_text("Show content", exact=True).click()
                recorder.snap("04 / Expand the exact content attached to the approval request", 1700)
                page.get_by_text("Hide content", exact=True).click()
                approve.scroll_into_view_if_needed()
                approve.hover()
                recorder.snap("05 / Approval stays in the user's hands", 900)
                approve.click()
                page.get_by_text("Approved at", exact=False).first.wait_for()
                assert fixture.approved.is_set(), "Approval never reached the local REST endpoint"
                recorder.snap("05 / The approval decision is reflected in the conversation", 1400)

                # Only make the fixture file available after the UI approval request succeeded.
                fixture.file_ready = True
                finish = fixture.start("report-builder", "-result")
                fixture.text(finish, "The approved report is ready to inspect in the Files panel. All figures in this walkthrough are fictional.")
                fixture.block(finish, {"block_id": "report-code", "type": "code", "language": "html",
                                       "filename": FILE_NAME, "code": REPORT, "old_code": "", "additions": 13, "deletions": 0})
                fixture.done(finish)
                fixture.emit("round_done")
                fixture.emit("queue_drained")
                page.wait_for_timeout(900)
                page.locator('.settings-btn').locator('..').locator('button.el-button').click()
                page.get_by_title("Workflow", exact=True).wait_for()
                # Use the actual layout controls to give the workflow and report room.
                page.locator('aside > button').click()
                page.wait_for_timeout(400)
                divider = page.locator('.splitpanes__splitter').first.bounding_box()
                assert divider, "The panel resize handle was not available"
                page.mouse.move(divider["x"] + divider["width"] / 2, 450)
                page.mouse.down()
                page.mouse.move(800, 450, steps=12)
                # Let the splitter's animation-frame resize finish before mouseup.
                page.wait_for_timeout(100)
                page.mouse.up()
                recorder.snap("06 / Review the recorded workflow alongside the conversation", 1900)
                page.get_by_title("Files", exact=True).click()
                page.get_by_text(FILE_NAME, exact=True).last.wait_for()
                recorder.snap("06 / Inspect the artifact in the session workspace", 1700)
                page.get_by_text(FILE_NAME, exact=True).last.click()
                page.wait_for_timeout(900)
                assert page.locator("iframe").count() > 0, "The real artifact preview was not opened"
                page.frame_locator("iframe").get_by_text("$300", exact=True).wait_for()
                recorder.snap("07 / Preview the report without leaving AgentHub", 2800)
                page.screenshot(path=str(args.output / "agenthub-report.png"))
                assert not fixture.unhandled, fixture.unhandled
                assert not errors, errors
                assert not blocked, blocked
                recorder.save(args.output)
                (args.output / "capture-checks.json").write_text(json.dumps({
                    "mode": "actual Vue UI, scripted local REST/SSE events", "date": "2026-11-23",
                    "viewport_css": [1440, 900], "device_scale_factor": 2,
                    "gif_size_px": [2400, 1740], "gif_dither": "none",
                    "request_submitted": fixture.submitted.is_set(), "approval_received": fixture.approved.is_set(),
                    "artifact_available_after_approval": fixture.file_ready,
                    "artifact_preview_rendered": True,
                    "browser_errors": errors, "unhandled_fixture_routes": fixture.unhandled,
                    "external_requests": blocked, "offline_font_stylesheets": sorted(set(offline_fonts)),
                    "requests": fixture.requests,
                }, indent=2) + "\n")
                print("Verified: UI submission, SSE rendering, approval POST, artifact preview, local-only requests.")
            except Exception:
                page.screenshot(path=str(args.output / "capture-failure.png"))
                print("Page text:", page.locator("body").inner_text()[-6000:])
                print("Browser errors:", errors, "Unhandled:", fixture.unhandled, "Blocked:", blocked)
                raise
            finally:
                browser.close()
    finally:
        fixture.closed.set()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
