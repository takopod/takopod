import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PID_FILE = DATA_DIR / "takopod.pid"


def _read_pid() -> int | None:
    if not PID_FILE.exists():
        return None
    pid = int(PID_FILE.read_text().strip())
    try:
        os.kill(pid, 0)
    except OSError:
        PID_FILE.unlink(missing_ok=True)
        return None
    return pid


def _find_pid_by_port(port: int) -> int | None:
    """Find PID of process listening on the given port via lsof."""
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip().splitlines()[0])
    except (OSError, subprocess.TimeoutExpired, ValueError):
        pass
    return None


def start(host: str = "0.0.0.0", port: int = 8000) -> None:
    existing = _read_pid()
    if existing:
        print(f"takopod is already running (pid {existing})")
        sys.exit(1)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log_file = DATA_DIR / "takopod.log"

    try:
        log = open(log_file, "a")  # noqa: SIM115
    except OSError as exc:
        print(f"Error: cannot open log file {log_file}: {exc}")
        sys.exit(1)

    project_root = Path(__file__).resolve().parent.parent

    try:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "orchestrator.main:app",
                "--host",
                host,
                "--port",
                str(port),
            ],
            cwd=project_root,
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        log.close()
        print(f"Error: failed to start takopod: {exc}")
        sys.exit(1)

    PID_FILE.write_text(str(proc.pid))
    print(f"takopod starting on {host}:{port} (pid {proc.pid})...")

    # Wait for the app to become ready
    url = f"http://{host}:{port}/api/health"
    for attempt in range(20):
        # Check if process died during startup
        if proc.poll() is not None:
            PID_FILE.unlink(missing_ok=True)
            print(f"Error: process exited during startup (code {proc.returncode})")
            print(f"Check logs: {log_file}")
            sys.exit(1)
        try:
            urllib.request.urlopen(url, timeout=2)
            print(f"takopod ready on http://{host}:{port}")
            print(f"Logs: {log_file}")
            return
        except (urllib.error.URLError, OSError):
            time.sleep(1)

    print(f"Warning: takopod started but health check not responding after 20s")
    print(f"Check logs: {log_file}")


def _kill_and_wait(pid: int) -> None:
    """Send SIGTERM to the orchestrator process and wait for it to exit.

    Only signals the orchestrator PID — not the process group — so that
    the FastAPI lifespan shutdown handler can cleanly stop workers and
    MCP servers without killing unrelated children (e.g. Chrome launched
    by the Playwright MCP server).
    """
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return

    print(f"takopod stopping (pid {pid})...")
    for _ in range(10):
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(1)

    # Still alive after 10s — escalate to SIGKILL
    print(f"Process {pid} did not exit, sending SIGKILL...")
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def stop(port: int = 8000) -> None:
    pid = _read_pid()
    if not pid:
        # PID file missing — check if something is still on the port
        pid = _find_pid_by_port(port)
        if not pid:
            print("takopod is not running")
            sys.exit(1)
        print(f"takopod pid file missing but found process {pid} on port {port}")

    try:
        _kill_and_wait(pid)
    except PermissionError:
        print(f"Error: permission denied stopping process {pid}")
        sys.exit(1)
    except OSError as exc:
        print(f"Error: failed to stop takopod (pid {pid}): {exc}")
        sys.exit(1)

    PID_FILE.unlink(missing_ok=True)

    # Kill any orphaned worker still bound to the port
    orphan = _find_pid_by_port(port)
    if orphan and orphan != pid:
        try:
            _kill_and_wait(orphan)
        except OSError:
            pass

    print("takopod stopped")


def status() -> None:
    pid = _read_pid()
    if not pid:
        print("takopod is not running")
        sys.exit(1)

    print(f"takopod is running (pid {pid})")

    # Read port from PID file's sibling or try default
    port = 8000
    try:
        resp = urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/health", timeout=5
        )
        data = json.loads(resp.read())
        print(f"  schema version: {data.get('schema_version')}")
    except (urllib.error.URLError, OSError):
        print("  health endpoint not responding")

    # Count managed containers
    podman = "/opt/podman/bin/podman"
    try:
        result = subprocess.run(
            [podman, "ps", "-a", "--filter", "label=takopod.managed=true",
             "--format", "{{.Status}}"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().splitlines()
            running = sum(1 for l in lines if l.startswith("Up"))
            stopped = len(lines) - running
            print(f"  containers: {running} running, {stopped} stopped")
        else:
            print("  containers: 0")
    except (OSError, subprocess.TimeoutExpired):
        print("  containers: unable to query podman")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: takopod <start|stop|status>")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "start":
        host = "0.0.0.0"
        port = 8000
        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] in ("--host", "-h") and i + 1 < len(args):
                host = args[i + 1]
                i += 2
            elif args[i] in ("--port", "-p") and i + 1 < len(args):
                try:
                    port = int(args[i + 1])
                except ValueError:
                    print(f"Error: invalid port number: {args[i + 1]}")
                    sys.exit(1)
                i += 2
            else:
                print(f"Unknown argument: {args[i]}")
                sys.exit(1)
        start(host, port)
    elif cmd == "stop":
        stop()
    elif cmd == "status":
        status()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
