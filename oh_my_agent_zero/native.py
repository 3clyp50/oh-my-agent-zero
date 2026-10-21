"""Narrow runtime adaptations; the upstream checkout stays byte-for-byte intact."""

import argparse
import asyncio
import base64
from dataclasses import replace
import functools
import inspect
import json
import os
from pathlib import Path
import platform
import shlex
import sys


def shell_command(arguments, windows=None):
    if windows is None:
        windows = os.name == "nt"
    if windows:
        return "& " + " ".join("'" + str(arg).replace("'", "''") + "'" for arg in arguments)
    return shlex.join(map(str, arguments))


def terminal_command():
    if os.name == "nt":
        return "powershell.exe -NoLogo -NoProfile"
    # macOS /bin/sh strips an inherited PS1 before spawning the interactive Bash.
    return shlex.join(["env", "PS1=a0@native:\\w$ ", "/bin/bash", "--noprofile", "--norc", "-i"])


def native_path(path, source):
    path = str(path)
    if path == "/a0":
        return str(source)
    if path.startswith("/a0/"):
        return str(source / path[4:])
    return str(source / path) if not os.path.isabs(path) else path


def map_alias(value, source):
    if isinstance(value, str) and (value == "/a0" or value.startswith("/a0/")):
        return native_path(value, source)
    if isinstance(value, list):
        return [map_alias(item, source) for item in value]
    return value


def execution_command(kind, code, source):
    encoded = base64.b64encode(code.encode("utf-8")).decode("ascii")
    if kind == "python":
        script = ("import base64; from IPython import start_ipython; "
                  f"start_ipython(argv=['-c',base64.b64decode('{encoded}').decode('utf-8')])")
        return shell_command([os.environ["OMA0_EXECUTION_PYTHON"], "-c", script])
    helper = str(source / "docker/run/fs/exe/node_eval.js")
    script = (f"process.argv[2]='(async()=>{{'+Buffer.from('{encoded}','base64').toString('utf8')+'\\n}})()';"
              f"require({json.dumps(helper)});")
    return shell_command([os.environ["OMA0_NODE"], "-e", script])


def adapt_code_execution(cet, source):
    if getattr(cet, "_oma0_applied", False):
        return
    for method in ("execute_python_code", "execute_nodejs_code", "terminal_session"):
        if not {"cfg", "session", "reset"}.issubset(inspect.signature(getattr(cet.CodeExecution, method)).parameters):
            raise RuntimeError(f"Unsupported upstream CodeExecution.{method} interface. Update the launcher.")
    original_ssh = cet._resolve_ssh_enabled
    cet._resolve_ssh_enabled = lambda value: False if str(value).lower().strip() == "auto" else original_ssh(value)
    original_python = cet.CodeExecution.execute_python_code
    original_node = cet.CodeExecution.execute_nodejs_code

    async def execute_python(self, cfg, session, code, reset=False):
        if cfg["ssh_enabled"]:
            return await original_python(self, cfg, session, code, reset)
        return await self.terminal_session(cfg, session, execution_command("python", code, source), reset, "python> " + self.format_command_for_output(code) + "\n\n")

    async def execute_node(self, cfg, session, code, reset=False):
        if cfg["ssh_enabled"]:
            return await original_node(self, cfg, session, code, reset)
        return await self.terminal_session(cfg, session, execution_command("nodejs", code, source), reset, "node> " + self.format_command_for_output(code) + "\n\n")

    cet.CodeExecution.execute_python_code = execute_python
    cet.CodeExecution.execute_nodejs_code = execute_node
    cet._oma0_applied = True


def apply(source):
    source = source.resolve()
    os.chdir(source)
    sys.path.insert(0, str(source))
    from helpers import files, runtime

    if getattr(runtime, "_oma0_applied", False):
        return
    runtime._oma0_applied = True
    runtime.initialize()
    runtime.args.pop("dockerized", None)
    runtime.is_development = lambda: False
    runtime.get_terminal_executable = terminal_command
    files.get_abs_path_dockerized = files.get_abs_path
    files.normalize_a0_path = lambda path: native_path(path, source)
    files.fix_dev_path = lambda path: native_path(path, source)
    original_resolve = files._resolve_path
    files._resolve_path = lambda *parts: original_resolve(*(map_alias(part, source) for part in parts))
    from helpers import rfc_files
    rfc_files.get_abs_path = files.get_abs_path
    original_call = runtime.call_development_function

    @functools.wraps(original_call)
    async def local_call(func, *args, **kwargs):
        bound = inspect.signature(func).bind(*args, **kwargs)
        for name, value in bound.arguments.items():
            if name in {"path", "paths", "relative_path", "absolute_path", "file_path", "current_path",
                        "parent_path", "source_path", "destination_path", "src", "dst"}:
                bound.arguments[name] = map_alias(value, source)
        return await original_call(func, *bound.args, **bound.kwargs)

    runtime.call_development_function = local_call

    original_prompt = files.read_prompt_file

    @functools.wraps(original_prompt)
    def read_prompt(_file, *args, **kwargs):
        if Path(_file).name == "agent.system.main.environment.md":
            return (
                f"## Environment\nYou run directly on {platform.system()} {platform.machine()}, "
                f"as the current OS user, outside Docker.\nFramework directory: {source}\n"
                f"Shell: {'PowerShell' if os.name == 'nt' else 'Bash'}. Use this OS's syntax and native paths.\n"
                f"Task Python: {os.environ['OMA0_EXECUTION_PYTHON']}\n"
                f"Framework Python: {sys.executable}\n"
                "Install task packages into task Python; keep framework dependencies separate.\n"
                "Terminal, Python, Node.js, and file tools operate directly on this computer with "
                "the user's permissions. There is no container sandbox or assumed root access.\n"
                "The Docker Linux desktop and Office desktop viewer are unavailable. "
                "Browser automation uses local Chromium; use screenshots and DOM tools.\n"
            )
        return original_prompt(_file, *args, **kwargs)

    files.read_prompt_file = read_prompt

    from plugins._code_execution.tools import code_execution_tool as cet
    adapt_code_execution(cet, source)
    from agent import Agent
    original_user_message = Agent.hist_add_user_message

    @functools.wraps(original_user_message)
    def user_message(self, message, *args, **kwargs):
        message = replace(message, attachments=[native_path(path, source) for path in message.attachments])
        return original_user_message(self, message, *args, **kwargs)

    Agent.hist_add_user_message = user_message
    from helpers import modules
    original_import = modules.import_module
    code_file = source / "plugins/_code_execution/tools/code_execution_tool.py"

    @functools.wraps(original_import)
    def import_module(file_path):
        module = original_import(file_path)
        if Path(module.__file__).resolve() == code_file:
            adapt_code_execution(module, source)
        canonical = sys.modules.get("plugins._code_execution.tools.code_execution_tool")
        if canonical is not None:
            adapt_code_execution(canonical, source)
        return module

    modules.import_module = import_module

    # Preserve the existing search tool's result contract without a SearXNG daemon.
    from helpers import searxng

    async def search(query):
        if url := os.environ.get("OMA0_SEARXNG_URL"):
            import aiohttp
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.post(url, data={"q": query, "format": "json"}) as response:
                    response.raise_for_status()
                    return await response.json()
        from ddgs import DDGS
        rows = await asyncio.to_thread(lambda: list(DDGS(timeout=20).text(query, max_results=10)))
        return {"results": [{"title": row["title"], "url": row["href"], "content": row["body"]} for row in rows]}

    searxng.search = search

    # Upstream's browser cache discovery currently omits the macOS application bundle.
    from plugins._browser.helpers import playwright as browser_paths
    browser_paths.FULL_CHROMIUM_PATTERNS += (
        "chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium",
        "chromium-*/chrome-mac*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
    )

    from helpers import plugins, system_packages
    original_enabled = plugins.get_enabled_plugins

    @functools.wraps(original_enabled)
    def enabled_plugins(*args, **kwargs):
        return [name for name in original_enabled(*args, **kwargs) if name not in {"_desktop", "_office"}]

    plugins.get_enabled_plugins = enabled_plugins

    def no_container_packages(*args, **kwargs):
        raise RuntimeError("Docker system-package hooks are unavailable in native mode. Install OS dependencies yourself.")

    system_packages.run_runtime_apt = no_container_packages
    if os.environ.get("OMA0_SUPERVISED") == "1":
        from helpers import process
        process.restart_process = lambda: os._exit(75)


async def check(source):
    from helpers import files, runtime, settings, plugins
    from plugins._code_execution.helpers.shell_local import LocalInteractiveSession
    from plugins._code_execution.tools import code_execution_tool as cet
    from plugins._browser.helpers.playwright import get_playwright_binary
    from patchright.async_api import async_playwright
    import run_ui

    assert callable(run_ui.run)
    assert not runtime.is_dockerized() and not runtime.is_development()
    assert not cet._get_config(None)["ssh_enabled"], "Code execution must default to the local shell"
    assert Path(files.get_abs_path_dockerized("usr/workdir")) == source / "usr/workdir"
    assert settings.get_settings()["workdir_path"] != "/a0/usr/workdir"
    assert not {"_desktop", "_office"}.intersection(plugins.get_enabled_plugins(None))
    assert await runtime.call_development_function(lambda: "local") == "local"
    assert "outside Docker" in files.read_prompt_file("agent.system.main.environment.md")
    workdir = source / "usr/workdir"
    shell = LocalInteractiveSession(cwd=str(workdir))
    try:
        await shell.connect()
        for kind, code, expected in (
            ("python", "print('native-python-' + str(6 * 7)); print(\"quotes ' \\\" $ café\")", "native-python-42"),
            ("nodejs", "console.log('native-node-' + (6 * 7)); console.log(await Promise.resolve('await-ok'))", "native-node-42"),
        ):
            await shell.send_command(execution_command(kind, code, source))
            output = ""
            for _ in range(100):
                output, _ = await shell.read_output(timeout=0.2)
                if expected in output:
                    break
                await asyncio.sleep(0.1)
            assert expected in output, f"{kind} failed: {output}"
    finally:
        await shell.close()
    binary = get_playwright_binary()
    assert binary, "Chromium was not installed"
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(executable_path=str(binary), headless=True)
        try:
            page = await browser.new_page()
            await page.goto("data:text/html,<h1>native-browser-ok</h1>")
            assert await page.locator("h1").inner_text() == "native-browser-ok"
        finally:
            await browser.close()
    print("Native checks passed: framework imports, paths, local calls, Bash/PowerShell, Python, Node.js, Chromium.", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--port", type=int, default=50001)
    args = parser.parse_args()
    source = args.source.resolve()
    apply(source)
    from helpers import dotenv, runtime
    dotenv.load_dotenv()
    runtime.args["host"] = "127.0.0.1"
    runtime.args["port"] = args.port
    if args.check:
        asyncio.run(check(source))
    else:
        import run_ui
        run_ui.run()


if __name__ == "__main__":
    main()
