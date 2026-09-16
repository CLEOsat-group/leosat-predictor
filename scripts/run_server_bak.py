# scripts/run_server.py
import os
import signal
import socket
import subprocess
import sys
import time

os.environ["PERSIST_TO_SQLITE"] = "1"

processes = []

def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def _terminate_process_group(pid, sig=signal.SIGTERM, wait=5.0):
    import os
    try:
        pgid = os.getpgid(pid)
        os.killpg(pgid, sig)
    except ProcessLookupError:
        return
    except PermissionError:
        try:
            os.kill(pid, sig)
        except Exception:
            pass
    # wait a bit
    t0 = time.time()
    while time.time() - t0 < wait:
        try:
            os.killpg(pgid, 0)
            time.sleep(0.1)
        except Exception:
            return

def cleanup(signum, frame):
    print(f"\nReceived signal {signum}. Terminating child processes...")
    for proc in processes:
        try:
            print(f"Terminating process group for: {proc.args}")
            _terminate_process_group(proc.pid, sig=signal.SIGTERM, wait=2.0)
        except Exception as e:
            print(f"Error terminating process {proc.args}: {e}")

    # escalate: kill any remaining gunicorn processes forcefully
    try:
        os.system("pkill -9 gunicorn")
    except Exception:
        pass

    # reap zombies
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
            if pid == 0:
                break
            print(f"Reaped PID {pid}")
        except ChildProcessError:
            break
        except Exception:
            break

    print("Cleanup complete. Exiting.")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    if is_port_in_use(8000):
        print("Gunicorn is already running on port 8000.")
    else:
        print("Starting Gunicorn server (WSGI Flask)...")

        env = os.environ.copy()
        env["PYTHONFAULTHANDLER"] = "1"
        env["PYTHONMALLOC"] = "debug"

        # Tuneable values
        GUNICORN_WORKERS = int(os.environ.get("GUNICORN_WORKERS", "2"))
        GUNICORN_THREADS = int(os.environ.get("GUNICORN_THREADS", "10"))

        # compute budget to export
        import multiprocessing
        TOTAL_CPUS = multiprocessing.cpu_count()
        total_compute_budget = max(1, TOTAL_CPUS - 1)
        per_worker_pool = max(1, total_compute_budget // max(1, GUNICORN_WORKERS))
        env["PREDICT_MAX_WORKERS"] = str(per_worker_pool)
        env["MAX_TIMES_PER_TASK"] = os.environ.get("MAX_TIMES_PER_TASK", "5000")

        gunicorn_args = [
            "gunicorn",
            "-w", str(GUNICORN_WORKERS),
            "-k", "gthread",
            "-b", "127.0.0.1:8000",
            "--threads", str(GUNICORN_THREADS),
            "--timeout", "30000",
            "--graceful-timeout", "100",
            "--log-level", "debug",
            "--capture-output",
            # do NOT use --preload when creating process pools inside workers
            # "--preload",
            "src.main:app",
        ]

        # Start process in its own process group so we can kill the group
        gunicorn_process = subprocess.Popen(gunicorn_args, env=env, preexec_fn=os.setsid)
        processes.append(gunicorn_process)

    # Wait for top-level process
    try:
        for p in processes:
            p.wait()
    except KeyboardInterrupt:
        cleanup(signal.SIGINT, None)
