import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "setup_openclaw_rufina_assistant.py"
)
SPEC = importlib.util.spec_from_file_location("setup_openclaw", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


class OpenClawSetupTests(unittest.TestCase):
    def configure(self, **kwargs):
        calls = []

        def run(command, *args):
            calls.append(args)
            if args[:3] == ("config", "get", "agents.list"):
                return json.dumps([{"id": setup.AGENT_ID}])
            if args[:3] == ("config", "get", "plugins.allow"):
                return '["existing-plugin"]'
            if args[:2] == ("config", "get"):
                return '[{"id":"existing-model","contextWindow":32768}]'
            return ""

        with patch.object(setup, "run_openclaw", side_effect=run):
            setup.configure_agent(
                "openclaw",
                Path("/unused-workspace"),
                kwargs.pop("model", setup.DEFAULT_MODEL),
                kwargs.pop("screening_model", setup.DEFAULT_SCREENING_MODEL),
                **kwargs,
            )
        batch = next(args for args in calls if args[:2] == ("config", "set"))
        operations = json.loads(batch[batch.index("--batch-json") + 1])
        return {operation["path"]: operation["value"] for operation in operations}, calls

    def assert_registered(self, operations, models):
        agent_models = operations["agents.list[0].models"]
        self.assertEqual(set(agent_models), set(models))
        for model in models:
            provider, model_id = model.split("/", 1)
            self.assertIn(f'agents.defaults.models["{model}"]', operations)
            self.assertIn(
                model_id,
                {
                    entry["id"]
                    for entry in operations[f'models.providers["{provider}"].models']
                },
            )
            self.assertEqual(agent_models[model], {"agentRuntime": {"id": "codex"}})

    def test_default_models_are_registered_at_every_permission_layer(self):
        operations, calls = self.configure()
        self.assert_registered(
            operations,
            {"openai/gpt-6.1-sol", "openai/gpt-6-luna", "openai/gpt-6-astra"},
        )
        self.assertIn(
            {"id": "existing-model", "contextWindow": 32768},
            operations['models.providers["openai"].models'],
        )
        self.assertEqual(operations["plugins.allow"], ["codex", "existing-plugin"])
        self.assertEqual(calls[-1], ("config", "validate"))

    def test_extra_model_can_use_another_provider_and_keep_legacy_opt_in(self):
        operations, calls = self.configure(
            allowed_models=["codex/custom-model", "openai/gpt-screening"]
        )
        self.assert_registered(
            operations,
            {
                setup.DEFAULT_MODEL,
                setup.DEFAULT_SCREENING_MODEL,
                "codex/custom-model",
                "openai/gpt-screening",
            },
        )
        self.assertNotIn(
            ("config", "unset", 'agents.defaults.models["openai/gpt-screening"]'),
            calls,
        )

    def test_primary_model_can_also_screen_without_duplicate_registration(self):
        operations, _ = self.configure(screening_model=setup.DEFAULT_MODEL)
        self.assert_registered(operations, {setup.DEFAULT_MODEL, "openai/gpt-6-astra"})
        model_ids = [
            entry["id"] for entry in operations['models.providers["openai"].models']
        ]
        self.assertEqual(model_ids.count("gpt-6.1-sol"), 1)

    def test_cli_allow_model_is_repeatable_and_keeps_astra(self):
        with (
            patch.object(
                setup.sys,
                "argv",
                ["setup", "--allow-model", "codex/one", "--allow-model", "codex/two"],
            ),
            patch.object(setup.shutil, "which", return_value="/usr/bin/openclaw"),
            patch.object(setup, "install_workspace", return_value=Path("/unused")),
            patch.object(setup, "configure_agent") as configure,
            patch("builtins.print"),
        ):
            self.assertEqual(setup.main(), 0)
        self.assertEqual(
            configure.call_args.args[-1],
            ["openai/gpt-6-astra", "codex/one", "codex/two"],
        )


if __name__ == "__main__":
    unittest.main()
