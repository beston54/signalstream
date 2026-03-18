import argparse
import unittest
from unittest import mock

import scripts.main as main_module


class MainCliFlagTests(unittest.TestCase):
    def test_only_report_reuses_existing_analyzed_and_themes_files(self):
        args = argparse.Namespace(
            config="config.yaml",
            dry_run=False,
            skip_collection=False,
            skip_analysis=False,
            skip_thematic=False,
            only_report=True,
            verbose=False,
            no_cleanup=True,
        )
        logger = mock.Mock()

        def fake_find_latest(_directory, prefix):
            mapping = {
                "posts_": "/tmp/posts.json",
                "analyzed_": "/tmp/analyzed.json",
                "themes_": "/tmp/themes.json",
            }
            return mapping[prefix]

        with mock.patch.object(main_module, "parse_arguments", return_value=args), \
             mock.patch.object(main_module, "load_config", return_value={"output": {"data_retention_days": 30}}), \
             mock.patch.object(main_module, "setup_logging", return_value=logger), \
             mock.patch.object(main_module, "validate_environment", return_value=[]), \
             mock.patch.object(main_module, "find_latest_file", side_effect=fake_find_latest), \
             mock.patch.object(main_module, "run_collection_phase") as run_collection, \
             mock.patch.object(main_module, "run_analysis_phase") as run_analysis, \
             mock.patch.object(main_module, "run_thematic_phase") as run_thematic, \
             mock.patch.object(main_module, "run_report_phase", return_value="/tmp/report.pdf") as run_report, \
             mock.patch("builtins.print"):
            main_module.main()

        self.assertTrue(args.skip_collection)
        self.assertTrue(args.skip_analysis)
        self.assertTrue(args.skip_thematic)
        run_collection.assert_not_called()
        run_analysis.assert_not_called()
        run_thematic.assert_not_called()
        run_report.assert_called_once_with("/tmp/analyzed.json", "/tmp/themes.json", mock.ANY, logger)


if __name__ == "__main__":
    unittest.main()
