"""Prepare heavyweight upstream features on first use, preserving base versions."""

import ast
import asyncio
import functools
import hashlib
import importlib
import importlib.abc
import importlib.machinery
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading

FEATURE_PACKAGES = {
    "speech-input": "openai-whisper",
    "speech-output": "kokoro",
    "documents": "unstructured",
}
BASIC_DOCUMENT_TYPES = {
    "text/plain", "text/html", "text/csv", "text/tab-separated-values",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
}
LOCK = threading.RLock()
ESPEAK_DATA_DIRECTORY = None


def split_requirements(source):
    base, optional = [], {}
    for line in (source / "requirements.txt").read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([a-zA-Z0-9_-]+)", line.strip())
        name = match[1].lower().replace("_", "-") if match else ""
        if name in FEATURE_PACKAGES.values():
            optional[name] = line
            if name == "unstructured":
                if "[all-docs]" not in line:
                    raise RuntimeError("Upstream Unstructured extras changed. Update the native launcher.")
                base.append(line.replace("[all-docs]", "[csv,docx,pptx,tsv,xlsx]", 1))
        else:
            base.append(line)
    if set(optional) != set(FEATURE_PACKAGES.values()):
        raise RuntimeError("Upstream optional requirements changed. Update the native launcher.")
    return "\n".join(base) + "\n", optional


def notify(feature, text, failed=False):
    print(f"Native {feature}: {text}", flush=True)
    try:
        from helpers.notification import NotificationManager, NotificationPriority, NotificationType
        NotificationManager.send_notification(
            NotificationType.ERROR if failed else NotificationType.INFO,
            NotificationPriority.NORMAL, text, display_time=99 if failed else 30,
            group="native-feature-" + feature,
        )
    except Exception:
        # Notifications are unavailable before WebUI initialization.
        pass


def ensure(feature, source):
    if feature not in {*FEATURE_PACKAGES, "browser"}:
        raise ValueError(f"Unknown native feature: {feature}")
    source = Path(source)
    _, optional = split_requirements(source)
    requirements = [optional[FEATURE_PACKAGES[feature]]] if feature in FEATURE_PACKAGES else []
    if feature == "speech-output":
        from plugins._kokoro_tts import hooks
        requirements.extend(map(str, hooks._DEPENDENCIES))
    fingerprint = hashlib.sha256(("native-features-v1\n" + "\n".join(requirements)).encode()).hexdigest()
    with LOCK:
        folder = Path(sys.prefix) / "native-features"
        marker = folder / (feature + ".json")
        if marker.exists() and json.loads(marker.read_text(encoding="utf-8"))["requirements"] == fingerprint:
            if feature != "browser":
                return
            from plugins._browser.helpers.playwright import get_playwright_binary
            if get_playwright_binary():
                return
        folder.mkdir(parents=True, exist_ok=True)
        notify(feature, f"Preparing {feature} support. The first download may take several minutes…")
        try:
            if requirements:
                # Pin every installed package: optional features cannot upgrade the running framework.
                constraints = folder / "installed.txt"
                constraints.write_text("\n".join(sorted(
                    f"{d.metadata['Name']}=={d.version}" for d in importlib.metadata.distributions()
                )) + "\n", encoding="utf-8")
                subprocess.run([
                    os.environ.get("OMA0_UV", "uv"), "pip", "install", "--python", sys.executable, "--torch-backend", "cpu",
                    "--constraint", str(constraints), *requirements,
                ], check=True, timeout=1200)
            else:
                from plugins._browser.helpers.playwright import ensure_playwright_binary
                ensure_playwright_binary()
            importlib.invalidate_caches()
            if feature == "documents":
                prepare_document_data(source)
            pending = marker.with_suffix(".tmp")
            pending.write_text(json.dumps({"requirements": fingerprint}) + "\n", encoding="utf-8")
            pending.replace(marker)
        except Exception as exc:
            notify(feature, f"Could not prepare {feature}. Check the server log and retry: {exc}", failed=True)
            raise RuntimeError(f"Native {feature} setup failed; retry when downloads are available.") from exc
        notify(feature, f"{feature} support is ready.")


def prepare_document_data(source):
    import nltk
    with LOCK:
        folder = Path(source) / "tmp/nltk_data"
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name != "nt":
            folder.chmod(0o700)
        if str(folder) not in nltk.data.path:
            nltk.data.path.insert(0, str(folder))
        for name, resource in (("punkt_tab", "tokenizers/punkt_tab/english/"),
                               ("averaged_perceptron_tagger_eng", "taggers/averaged_perceptron_tagger_eng/")):
            try:
                nltk.data.find(resource, paths=[str(folder)])
            except LookupError:
                notify("documents", f"Preparing document text data: {name}…")
                if not nltk.download(name, download_dir=str(folder), quiet=True, raise_on_error=True):
                    raise RuntimeError(f"Could not download document tokenizer data: {name}")


def prepare_speech_data():
    global ESPEAK_DATA_DIRECTORY
    with LOCK:
        if ESPEAK_DATA_DIRECTORY is None:
            import espeakng_loader
            from phonemizer.backend.espeak.wrapper import EspeakWrapper
            # eSpeak silently falls back to its build machine's path for long native venv paths.
            folder = tempfile.TemporaryDirectory(prefix="a0-speech-")
            data = Path(folder.name) / "espeak-ng-data"
            shutil.copytree(espeakng_loader.get_data_path(), data)
            espeakng_loader.get_data_path = lambda: str(data)
            EspeakWrapper.set_data_path(str(data))
            ESPEAK_DATA_DIRECTORY = folder


def wrap_async(module, name, feature, source, whisper=False):
    original = getattr(module, name)

    @functools.wraps(original)
    async def prepared(*args, **kwargs):
        document = args[1] if len(args) > 1 else kwargs.get("document")
        if feature == "documents" and getattr(document, "mimetype", "") in BASIC_DOCUMENT_TYPES:
            await asyncio.to_thread(prepare_document_data, source)
        else:
            await asyncio.to_thread(ensure, feature, source)
        if feature == "speech-output":
            await asyncio.to_thread(prepare_speech_data)
        if whisper:
            module.whisper = importlib.import_module("whisper")
        return await original(*args, **kwargs)

    setattr(module, name, prepared)


def adapt(module, source):
    name = module.__name__
    if name == "magic.loader":
        original = module._lib_candidates

        def native_libraries():
            # Git's MSYS/Cygwin DLLs require their own runtime and can hang native CPython.
            for candidate in original():
                if candidate and any(part in str(candidate).lower() for part in ("msys-", "cygmagic", "cygwin")):
                    continue
                yield candidate

        module._lib_candidates = native_libraries
    elif name == "plugins._whisper_stt.helpers.runtime":
        wrap_async(module, "_preload", "speech-input", source, whisper=True)
    elif name == "plugins._kokoro_tts.helpers.runtime":
        for method in ("preload", "synthesize_sentences"):
            wrap_async(module, method, "speech-output", source)
    elif name == "plugins._kokoro_tts.hooks":
        # Upstream runs this at startup; actual synthesis/preload owns preparation here.
        module.ensure_dependencies = lambda raise_on_error=True: True
    elif name == "plugins._browser.helpers.runtime":
        wrap_async(module._BrowserRuntimeCore, "_start", "browser", source)
    elif name in {"plugins._document_query.helpers.parsers.unstructured", "plugins._document_query.helpers.parsers.image"}:
        parser = module.UnstructuredParser if name.endswith("unstructured") else module.ImageParser
        # Preparation precedes the upstream per-document parsing timeout.
        wrap_async(parser, "parse", "documents", source)


def adapt_dynamic(module, source):
    if Path(module.__file__).resolve() == source / "plugins/_browser/extensions/python/startup_migration/_20_browser_playwright_cache.py":
        module._start_background_cache_migration = lambda: None
    elif Path(module.__file__).resolve() == source / "plugins/_kokoro_tts/hooks.py":
        module.ensure_dependencies = lambda raise_on_error=True: True


class FeatureLoader(importlib.machinery.SourceFileLoader):
    def exec_module(self, module):
        if module.__name__ == "plugins._whisper_stt.helpers.runtime":
            tree = ast.parse(self.get_source(module.__name__), filename=self.path)
            imports = [node for node in tree.body if isinstance(node, ast.Import)
                       and len(node.names) == 1 and node.names[0].name == "whisper"
                       and node.names[0].asname is None]
            if len(imports) != 1:
                raise RuntimeError("Upstream Whisper imports changed. Update the native launcher.")
            tree.body.remove(imports[0])
            exec(compile(tree, self.path, "exec"), module.__dict__)
        else:
            super().exec_module(module)
        adapt(module, self.source)


class FeatureFinder(importlib.abc.MetaPathFinder):
    MODULES = {
        "plugins._whisper_stt.helpers.runtime", "plugins._kokoro_tts.helpers.runtime",
        "plugins._kokoro_tts.hooks", "plugins._browser.helpers.runtime",
        "plugins._document_query.helpers.parsers.unstructured", "plugins._document_query.helpers.parsers.image",
        "magic.loader",
    }

    def __init__(self, source):
        self.source = source

    def find_spec(self, fullname, path=None, target=None):
        if fullname == "magic.loader" and os.name != "nt":
            return None
        if fullname in self.MODULES:
            spec = importlib.machinery.PathFinder.find_spec(fullname, path)
            if spec and spec.origin:
                loader = FeatureLoader(fullname, spec.origin)
                loader.source = self.source
                spec.loader = loader
                return spec
        return None
