import asyncio
from concurrent.futures import ThreadPoolExecutor
import importlib.util
from pathlib import Path
import subprocess
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from oh_my_agent_zero import features


REQUIREMENTS = """# upstream requirements
torch>=2
openai-whisper==20250625
kokoro>=0.9.2
unstructured[all-docs]==0.16.23
cryptography>=46 # security floor
"""


class FeatureTests(unittest.TestCase):
    def test_base_preserves_core_and_security_constraints(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)
            (source / "requirements.txt").write_text(REQUIREMENTS)
            base, optional = features.split_requirements(source)
            self.assertIn("torch>=2", base)
            self.assertIn("cryptography>=46 # security floor", base)
            self.assertIn("unstructured[csv,docx,pptx,tsv,xlsx]==0.16.23", base)
            self.assertNotIn("all-docs", base)
            self.assertNotIn("kokoro", base)
            self.assertNotIn("whisper", base)
            self.assertEqual(optional["unstructured"], "unstructured[all-docs]==0.16.23")
            (source / "requirements.txt").write_text("torch>=2\n")
            with self.assertRaisesRegex(RuntimeError, "requirements changed"):
                features.split_requirements(source)

    def test_concurrent_first_use_installs_once_and_pins_running_packages(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)
            (source / "requirements.txt").write_text(REQUIREMENTS)
            dist = SimpleNamespace(metadata={"Name": "torch"}, version="2.14.1+cpu")

            def install(command, **kwargs):
                constraints = Path(command[command.index("--constraint") + 1])
                self.assertEqual(constraints.read_text(), "torch==2.14.1+cpu\n")
                self.assertIn("openai-whisper==20250625", command)
                self.assertNotIn("kokoro>=0.9.2", command)
                self.assertTrue(kwargs["check"])

            with patch.object(features.sys, "prefix", folder), patch.object(features.importlib.metadata, "distributions", return_value=[dist]), \
                    patch.object(features.subprocess, "run", side_effect=install) as run, patch.object(features, "notify"):
                with ThreadPoolExecutor(max_workers=4) as pool:
                    list(pool.map(lambda _: features.ensure("speech-input", source), range(8)))
                self.assertEqual(run.call_count, 1)

    def test_failed_download_can_be_retried_without_a_false_ready_marker(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)
            (source / "requirements.txt").write_text(REQUIREMENTS)
            with patch.object(features.sys, "prefix", folder), patch.object(features.importlib.metadata, "distributions", return_value=[]), \
                    patch.object(features.subprocess, "run", side_effect=[subprocess.CalledProcessError(1, "uv"), None]) as run, \
                    patch.object(features, "notify"), patch.object(features, "prepare_document_data") as assets:
                with self.assertRaisesRegex(RuntimeError, "setup failed"):
                    features.ensure("documents", source)
                self.assertFalse((source / "native-features/documents.json").exists())
                features.ensure("documents", source)
                self.assertTrue((source / "native-features/documents.json").exists())
                self.assertEqual(run.call_count, 2)
                assets.assert_called_once_with(source)

    def test_whisper_status_import_does_not_import_or_install_whisper(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "runtime.py"
            file.write_text("import whisper\nasync def _preload(name):\n    return whisper.load_model(name)\n")
            name = "plugins._whisper_stt.helpers.runtime"
            loader = features.FeatureLoader(name, str(file))
            loader.source = Path(folder)
            module = importlib.util.module_from_spec(importlib.util.spec_from_loader(name, loader))
            fake_whisper = SimpleNamespace(load_model=lambda name: "loaded-" + name)
            with patch.object(features, "ensure") as ensure, patch.object(features.importlib, "import_module", return_value=fake_whisper) as imported:
                loader.exec_module(module)
                ensure.assert_not_called()
                imported.assert_not_called()
                self.assertEqual(asyncio.run(module._preload("tiny")), "loaded-tiny")
                ensure.assert_called_once_with("speech-input", Path(folder))
                imported.assert_called_once_with("whisper")
            file.write_text("import another_whisper\n")
            with self.assertRaisesRegex(RuntimeError, "Whisper imports changed"):
                loader.exec_module(module)

    def test_document_preparation_precedes_parser_timeout_and_preserves_arguments(self):
        events = []

        class Parser:
            async def parse(self, document, config, timeout=60):
                events.append(("parse", document, config, timeout))
                return "document text"

        module = ModuleType("plugins._document_query.helpers.parsers.image")
        module.ImageParser = Parser
        with patch.object(features, "ensure", side_effect=lambda *args: events.append("prepare")):
            features.adapt(module, Path("source"))
            self.assertEqual(asyncio.run(Parser().parse("file", {"option": True}, timeout=2)), "document text")
        self.assertEqual(events, ["prepare", ("parse", "file", {"option": True}, 2)])

    def test_dynamic_startup_hooks_keep_optional_features_deferred(self):
        source = Path(tempfile.gettempdir()).resolve()
        for path, method in (
            ("plugins/_browser/extensions/python/startup_migration/_20_browser_playwright_cache.py", "_start_background_cache_migration"),
            ("plugins/_kokoro_tts/hooks.py", "ensure_dependencies"),
        ):
            module = SimpleNamespace(__file__=str(source / path))
            features.adapt_dynamic(module, source)
            with patch.object(features, "ensure") as ensure:
                getattr(module, method)()
                ensure.assert_not_called()

    def test_basic_office_documents_do_not_install_the_advanced_stack(self):
        class Parser:
            async def parse(self, document, config):
                return "basic office text"

        module = ModuleType("plugins._document_query.helpers.parsers.unstructured")
        module.UnstructuredParser = Parser
        document = SimpleNamespace(mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        with patch.object(features, "ensure") as ensure, patch.object(features, "prepare_document_data") as data:
            features.adapt(module, Path("source"))
            self.assertEqual(asyncio.run(Parser().parse(document=document, config={})), "basic office text")
            data.assert_called_once_with(Path("source"))
            ensure.assert_not_called()

    def test_windows_magic_uses_native_libraries_or_upstream_fallback(self):
        module = ModuleType("magic.loader")
        module._lib_candidates = lambda: iter([None, "C:/Git/usr/bin/msys-magic-1.dll", "cygmagic-1.dll", "C:/native/libmagic.dll"])
        features.adapt(module, Path("source"))
        self.assertEqual(list(module._lib_candidates()), [None, "C:/native/libmagic.dll"])


if __name__ == "__main__":
    unittest.main()
