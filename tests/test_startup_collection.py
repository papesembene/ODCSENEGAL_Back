"""Check collection selection in fresh processes without contacting MongoDB."""
import os
from pathlib import Path
import subprocess
import sys
import unittest


class StartupCollectionTest(unittest.TestCase):
    def check_collection(self, value, expected):
        environment = os.environ.copy()
        environment.pop("STARTUP_COLLECTION", None)
        if value is not None:
            environment["STARTUP_COLLECTION"] = value
        model = Path(__file__).resolve().parents[1] / "app/models/startup.py"
        result = subprocess.run(
            [sys.executable, "-c",
             "import runpy, sys; "
             "model = runpy.run_path(sys.argv[1])['Startup']; "
             "print(model._get_collection_name()); "
             "assert model._fields['founder_email'].unique; "
             "assert model._fields['startup_name'].unique", str(model)],
            env=environment, capture_output=True, text=True, check=True,
        )
        self.assertEqual(result.stdout.strip(), expected)

    def test_historical_collection_is_preserved_by_default(self):
        self.check_collection(None, "startup")

    def test_new_campaign_uses_separate_collection_and_unique_indexes(self):
        self.check_collection("startups_2026", "startups_2026")

    def test_next_campaign_can_be_selected_without_code_change(self):
        self.check_collection(" startups_2027 ", "startups_2027")

    def test_empty_configuration_refuses_to_start(self):
        with self.assertRaises(subprocess.CalledProcessError):
            self.check_collection(" ", "startup")
