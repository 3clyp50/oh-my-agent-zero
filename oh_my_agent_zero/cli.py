"""Dependency-free installer and launcher. All managed state lives under one home."""

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

UPSTREAM = "https://github.com/agent0ai/agent-zero.git"
ADAPTER = Path(__file__).with_name("native.py")


def run(*args, **kwargs):
    print("+", " ".join(map(str, args)), flush=True)
    return subprocess.run(list(map(str, args)), check=True, **kwargs)


def git(source, *args):
    return subprocess.check_output(
        ["git", "-C", str(source), *args], text=True, encoding="utf-8"
    ).strip()


def python_in(venv):
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def default_home():
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return Path(os.environ.get("OMA0_HOME", base / "oh-my-agent-zero")).expanduser().resolve()


@contextmanager
def locked(home):
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt":
        home.chmod(0o700)
    with (home / "runtime.lock").open("a+b") as handle:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("Agent Zero or another installer is running. Stop it first.") from exc
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("Agent Zero or another installer is running. Stop it first.") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


def read_state(home):
    path = home / "state.json"
    if not path.exists():
        raise RuntimeError("Run 'a0-native install' first.")
    return json.loads(path.read_text(encoding="utf-8"))


def save_state(home, state):
    target = home / "state.json"
    pending = target.with_suffix(".tmp")
    pending.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    pending.replace(target)


def environment(home, state):
    env = os.environ.copy()
    task_bin = python_in(home / "execution").parent
    node_bin = Path(state["node"]).parent
    env["PATH"] = os.pathsep.join([str(task_bin), str(node_bin), env.get("PATH", "")])
    env["VIRTUAL_ENV"] = str(home / "execution")
    env.pop("PYTHONHOME", None)
    env["PYTHONUTF8"] = "1"
    env["OMA0_EXECUTION_PYTHON"] = str(python_in(home / "execution"))
    env["OMA0_NODE"] = state["node"]
    env["OMA0_UV"] = state.get("uv", shutil.which("uv") or "uv")
    env["PLAYWRIGHT_BROWSERS_PATH"] = str(home / "browsers")
    env["A0_BROWSER_PLAYWRIGHT_CACHE_DIR"] = str(home / "browsers")
    env["NLTK_DATA"] = str(home / "source/tmp/nltk_data")
    if sys.platform == "darwin":
        # Keep the native ML libraries from creating competing CPU worker pools.
        for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
            env.setdefault(name, "1")
    return env


def adapter_command(home, state, *args):
    return [str(python_in(home / state["framework"])), str(ADAPTER),
            "--source", str(home / "source"), *args]


def seed_native_data(source):
    # These plugins manage system packages and Xpra services from the Docker image.
    for name in ("_desktop", "_office"):
        folder = source / "usr/plugins" / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / ".disabled").touch()
    (source / "usr/workdir").mkdir(parents=True, exist_ok=True)


def install(home, branch="main", update=False, progress=print):
    progress("Fetching the official Agent Zero source...")
    uv_bin = Path.home() / ".local/bin"
    if not shutil.which("uv") and (uv_bin / ("uv.exe" if os.name == "nt" else "uv")).is_file():
        os.environ["PATH"] = str(uv_bin) + os.pathsep + os.environ.get("PATH", "")
    for command in ("git", "uv"):
        if not shutil.which(command):
            raise RuntimeError(f"{command} is required. See the installation instructions.")
    source = home / "source"
    previous = read_state(home) if (home / "state.json").exists() else None
    if previous:
        branch = previous["branch"]
        if not update:
            print("Already installed. Use 'a0-native start' or 'a0-native update'.")
            return
    if not source.exists():
        run("git", "clone", "--depth", "1", "--branch", branch, UPSTREAM, source)
    if git(source, "remote", "get-url", "origin").removesuffix(".git") != UPSTREAM.removesuffix(".git"):
        raise RuntimeError("The managed checkout does not point to the official upstream repository.")
    if git(source, "status", "--porcelain", "--untracked-files=no"):
        raise RuntimeError("The upstream checkout has local changes. Save them before updating.")
    old_revision = git(source, "rev-parse", "HEAD")
    if previous and old_revision != previous["revision"]:
        raise RuntimeError("The managed checkout revision changed outside the launcher.")
    run("git", "-C", source, "fetch", "origin", branch)
    revision = git(source, "rev-parse", "FETCH_HEAD")
    if previous:
        run("git", "-C", source, "merge-base", "--is-ancestor", old_revision, revision)
    adapter_version = hashlib.sha256(b"".join(path.name.encode() + path.read_bytes()
                                             for path in sorted(ADAPTER.parent.glob("*.py")))).hexdigest()[:12]
    framework = Path("environments") / (revision + "-" + adapter_version) / "framework"
    if previous and revision == previous["revision"] and str(framework) == previous["framework"]:
        run(*adapter_command(home, previous, "--check"), env=environment(home, previous))
        print("Upstream is current; native checks passed.")
        return
    state = {"revision": revision, "branch": branch, "framework": str(framework), "uv": shutil.which("uv")}
    try:
        run("git", "-C", source, "checkout", "--detach", revision)
        progress("Preparing framework Python and core dependencies...")
        if not python_in(home / framework).exists():
            run("uv", "venv", "--seed", "--python", "3.12", home / framework)
        py = python_in(home / framework)
        from oh_my_agent_zero.features import split_requirements
        base, _ = split_requirements(source)
        requirements = (home / framework).parent / "base-requirements.txt"
        requirements.parent.mkdir(parents=True, exist_ok=True)
        requirements.write_text(base, encoding="utf-8")
        run("uv", "pip", "install", "--python", py, "--torch-backend", "cpu",
            "-r", requirements, "ddgs>=9,<10", "nodeenv>=1.9,<2", "timm>=1,<2")
        progress("Preparing the separate Python execution runtime...")
        if not python_in(home / "execution").exists():
            run("uv", "venv", "--seed", "--python", "3.13", home / "execution")
        run("uv", "pip", "install", "--python", python_in(home / "execution"), "ipython", "requests")
        node = shutil.which("node")
        progress("Checking Node.js...")
        if not node:
            node = str(home / "node" / ("Scripts/node.exe" if os.name == "nt" else "bin/node"))
            if not Path(node).exists():
                run(py, "-m", "nodeenv", "--node=lts", "--prebuilt", home / "node")
        state["node"] = node
        env = environment(home, state)
        seed_native_data(source)
        progress("Verifying the upstream runtime and local code execution...")
        run(*adapter_command(home, state, "--check"), env=env)
        save_state(home, state)
    except BaseException:
        run("git", "-C", source, "checkout", "--detach", old_revision)
        raise
    print(f"Ready: upstream {revision[:12]} ({branch})\nData: {source / 'usr'}\nRun: a0-native start")


def serve(home, state, port):
    env = environment(home, state)
    env["OMA0_SUPERVISED"] = "1"
    command = adapter_command(home, state, "--port", str(port))
    while True:
        child = subprocess.Popen(command, env=env)
        try:
            code = child.wait()
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
        if code != 75:
            if code:
                raise subprocess.CalledProcessError(code, command)
            return


def main(argv=None):
    parser = argparse.ArgumentParser(description="Agent Zero, running directly on your machine.")
    parser.add_argument("--home", type=Path, default=default_home(), help="Managed installation directory")
    sub = parser.add_subparsers(dest="command", required=True)
    setup = sub.add_parser("install", help="Install upstream and isolated runtimes")
    setup.add_argument("--branch", choices=("main", "development"), default="main")
    sub.add_parser("update", help="Prepare the latest upstream commit; preserve data")
    start = sub.add_parser("start", help="Run in the foreground; Ctrl+C stops the server")
    start.add_argument("--port", type=int, default=50001)
    start.add_argument("--no-browser", action="store_true", help="Do not open the first-start setup page automatically")
    sub.add_parser("doctor", help="Verify the actual upstream runtime and native adapter")
    sub.add_parser("status", help="Show the active revision and data location")
    args = parser.parse_args(argv)
    home = args.home.expanduser().resolve()
    try:
        if args.command == "start" and not 1 <= args.port <= 65535:
            raise RuntimeError("Port must be between 1 and 65535.")
        if args.command == "status":
            state = read_state(home)
            print(json.dumps({**state, "home": str(home), "data": str(home / "source/usr")}, indent=2))
            return
        with locked(home):
            if args.command in ("install", "update"):
                install(home, getattr(args, "branch", "main"), args.command == "update")
            else:
                if args.command == "start" and not (home / "state.json").exists():
                    from oh_my_agent_zero.setup_ui import setup_page
                    with setup_page(args.port, open_browser=not args.no_browser) as progress:
                        install(home, progress=progress)
                state = read_state(home)
                if git(home / "source", "rev-parse", "HEAD") != state["revision"]:
                    raise RuntimeError("Checkout revision does not match the installed environment.")
                if args.command == "start":
                    print(f"Agent Zero: http://127.0.0.1:{args.port}\nCommands run on this machine as your user.", flush=True)
                    serve(home, state, args.port)
                else:
                    run(*adapter_command(home, state, "--check"), env=environment(home, state))
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
