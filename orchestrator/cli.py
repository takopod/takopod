import os
import signal
import subprocess
import sys
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PID_FILE = DATA_DIR / "rhclaw.pid"


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


def start(host: str = "0.0.0.0", port: int = 8000) -> None:
    existing = _read_pid()
    if existing:
        print(f"rhclaw is already running (pid {existing})")
        sys.exit(1)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log_file = DATA_DIR / "rhclaw.log"

    log = open(log_file, "a")  # noqa: SIM115
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
        stdout=log,
        stderr=log,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )

    PID_FILE.write_text(str(proc.pid))
    print(f"rhclaw started on {host}:{port} (pid {proc.pid})")
    print(f"Logs: {log_file}")


def stop() -> None:
    pid = _read_pid()
    if not pid:
        print("rhclaw is not running")
        sys.exit(1)

    os.kill(pid, signal.SIGTERM)
    PID_FILE.unlink(missing_ok=True)
    print(f"rhclaw stopped (pid {pid})")


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: rhclaw <start|stop>")
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
                port = int(args[i + 1])
                i += 2
            else:
                print(f"Unknown argument: {args[i]}")
                sys.exit(1)
        start(host, port)
    elif cmd == "stop":
        stop()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
