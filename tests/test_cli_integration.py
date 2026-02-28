import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

try:
    from yaml_injektr.cli import main
except ModuleNotFoundError as exc:
    if getattr(exc, "name", None) == "yaml_injektr":
        raise ModuleNotFoundError(
            "yaml_injektr is not installed. Run: python -m pip install -e .  (or: python -m pip install .)"
        ) from exc
    raise


class CliIntegrationTests(unittest.TestCase):
    def run_cli(self, argv):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def parse_jsonl(self, text):
        lines = [line for line in text.splitlines() if line.strip()]
        return [json.loads(line) for line in lines]

    def test_dry_run_outputs_json_and_summary_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            note = root / "note.md"
            payload = root / "payload.yaml"
            note.write_text("Body\n", encoding="utf-8")
            payload.write_text("title: DryRun\n", encoding="utf-8")

            code, out, err = self.run_cli(["--target", str(note), "--payload", str(payload)])

            self.assertEqual(code, 0)
            self.assertEqual(note.read_text(encoding="utf-8"), "Body\n")
            records = self.parse_jsonl(out)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["status"], "changed")
            self.assertIn("scanned: 1", err)
            self.assertIn("changed: 1", err)

    def test_apply_writes_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            note = root / "note.md"
            payload = root / "payload.yaml"
            note.write_text("Body\n", encoding="utf-8")
            payload.write_text("title: Applied\n", encoding="utf-8")

            code, out, err = self.run_cli(
                ["--target", str(note), "--payload", str(payload), "--apply"]
            )

            self.assertEqual(code, 0)
            self.assertIn("---\ntitle: Applied\n---\nBody\n", note.read_text(encoding="utf-8"))
            records = self.parse_jsonl(out)
            self.assertEqual(records[0]["status"], "changed")
            self.assertIn("mode: apply", err)

    def test_no_json_and_no_summary_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            note = root / "note.md"
            payload = root / "payload.yaml"
            note.write_text("Body\n", encoding="utf-8")
            payload.write_text("title: Silent\n", encoding="utf-8")

            code, out, err = self.run_cli(
                [
                    "--target",
                    str(note),
                    "--payload",
                    str(payload),
                    "--no-json",
                    "--no-summary",
                ]
            )

            self.assertEqual(code, 0)
            self.assertEqual(out, "")
            self.assertEqual(err, "")

    def test_exit_code_two_when_any_file_errors(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            good = root / "good.md"
            bad = root / "bad.md"
            payload = root / "payload.yaml"
            good.write_text("Good\n", encoding="utf-8")
            bad.write_text("---\nuuid: broken\nno close", encoding="utf-8")
            payload.write_text("title: Run\n", encoding="utf-8")

            code, out, _ = self.run_cli(["--target", str(root), "--payload", str(payload)])

            self.assertEqual(code, 2)
            records = self.parse_jsonl(out)
            self.assertEqual(len(records), 2)
            statuses = {record["path"]: record["status"] for record in records}
            self.assertEqual(statuses[str(bad)], "error")
            self.assertEqual(statuses[str(good)], "changed")

    def test_exclude_dir_defaults_and_override_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            hidden_dir = root / ".obsidian"
            tmp_dir = root / "tmp"
            hidden_dir.mkdir(parents=True)
            tmp_dir.mkdir(parents=True)

            visible = root / "visible.md"
            hidden = hidden_dir / "hidden.md"
            tmp_note = tmp_dir / "tmp.md"
            payload = root / "payload.yaml"

            visible.write_text("Visible\n", encoding="utf-8")
            hidden.write_text("Hidden\n", encoding="utf-8")
            tmp_note.write_text("Tmp\n", encoding="utf-8")
            payload.write_text("title: Test\n", encoding="utf-8")

            code_default, out_default, err_default = self.run_cli(
                ["--target", str(root), "--payload", str(payload)]
            )
            self.assertEqual(code_default, 0)
            default_records = self.parse_jsonl(out_default)
            default_paths = {record["path"] for record in default_records}
            self.assertIn(str(visible), default_paths)
            self.assertIn(str(tmp_note), default_paths)
            self.assertNotIn(str(hidden), default_paths)
            self.assertTrue(
                any(
                    r["status"] == "skipped" and r["path"] == str(hidden_dir) and r.get("is_dir")
                    for r in default_records
                )
            )
            self.assertIn("skipped: 1", err_default)

            code_override, out_override, err_override = self.run_cli(
                [
                    "--target",
                    str(root),
                    "--payload",
                    str(payload),
                    "--no-default-excludes",
                    "--exclude-dir",
                    "tmp",
                ]
            )
            self.assertEqual(code_override, 0)
            override_records = self.parse_jsonl(out_override)
            override_paths = {record["path"] for record in override_records}
            self.assertIn(str(visible), override_paths)
            self.assertIn(str(hidden), override_paths)
            self.assertNotIn(str(tmp_note), override_paths)
            self.assertTrue(
                any(
                    r["status"] == "skipped" and r["path"] == str(tmp_dir) and r.get("is_dir")
                    for r in override_records
                )
            )
            self.assertIn("skipped: 1", err_override)

    def test_exclude_matching_is_case_insensitive_on_windows(self) -> None:
        if os.name != "nt":
            self.skipTest("Windows-only behavior")

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            odd_case = root / ".Obsidian"
            odd_case.mkdir(parents=True)

            visible = root / "visible.md"
            hidden = odd_case / "hidden.md"
            payload = root / "payload.yaml"

            visible.write_text("Visible\n", encoding="utf-8")
            hidden.write_text("Hidden\n", encoding="utf-8")
            payload.write_text("title: Test\n", encoding="utf-8")

            code, out, err = self.run_cli(["--target", str(root), "--payload", str(payload)])
            self.assertEqual(code, 0)
            records = self.parse_jsonl(out)
            paths = {record["path"] for record in records}
            self.assertIn(str(visible), paths)
            self.assertNotIn(str(hidden), paths)
            self.assertTrue(
                any(
                    r["status"] == "skipped" and r["path"] == str(odd_case) and r.get("is_dir")
                    for r in records
                )
            )
            self.assertIn("skipped: 1", err)

    def test_glob_star_md_is_root_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            nested = root / "sub"
            nested.mkdir(parents=True)

            root_md = root / "a.md"
            nested_md = nested / "b.md"
            payload = root / "payload.yaml"

            root_md.write_text("Root\n", encoding="utf-8")
            nested_md.write_text("Nested\n", encoding="utf-8")
            payload.write_text("title: Test\n", encoding="utf-8")

            code, out, _ = self.run_cli(
                ["--target", str(root), "--payload", str(payload), "--glob", "*.md"]
            )
            self.assertEqual(code, 0)
            records = self.parse_jsonl(out)
            paths = {record["path"] for record in records}
            self.assertIn(str(root_md), paths)
            self.assertNotIn(str(nested_md), paths)

    def test_glob_doublestar_md_is_recursive_including_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            nested = root / "sub"
            nested.mkdir(parents=True)

            root_md = root / "a.md"
            nested_md = nested / "b.md"
            payload = root / "payload.yaml"

            root_md.write_text("Root\n", encoding="utf-8")
            nested_md.write_text("Nested\n", encoding="utf-8")
            payload.write_text("title: Test\n", encoding="utf-8")

            code, out, _ = self.run_cli(
                ["--target", str(root), "--payload", str(payload), "--glob", "**/*.md"]
            )
            self.assertEqual(code, 0)
            records = self.parse_jsonl(out)
            paths = {record["path"] for record in records}
            self.assertIn(str(root_md), paths)
            self.assertIn(str(nested_md), paths)

    def test_invalid_wrapped_payload_returns_usage_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            note = root / "note.md"
            payload = root / "payload.yaml"
            note.write_text("Body\n", encoding="utf-8")
            payload.write_text("---\ntitle: bad\n", encoding="utf-8")

            code, out, err = self.run_cli(["--target", str(note), "--payload", str(payload)])

            self.assertEqual(code, 1)
            self.assertEqual(out, "")
            self.assertIn("invalid payload", err)

    def test_file_date_token_parses_from_year_month_folder_and_day_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            month_dir = root / "2025-12"
            month_dir.mkdir(parents=True)

            monday = month_dir / "03_monday.md"
            tuesday = month_dir / "04_tuesday.md"
            payload = root / "payload.yaml"

            monday.write_text("Body Monday\n", encoding="utf-8")
            tuesday.write_text("Body Tuesday\n", encoding="utf-8")
            payload.write_text(
                'journal_entry_date: "{file_date}"\n'
                "title: Test\n",
                encoding="utf-8",
            )

            code, out, _ = self.run_cli(
                ["--target", str(month_dir), "--payload", str(payload), "--apply"]
            )

            self.assertEqual(code, 0)
            monday_text = monday.read_text(encoding="utf-8")
            tuesday_text = tuesday.read_text(encoding="utf-8")
            self.assertIn("journal_entry_date: \"2025-12-03\"", monday_text)
            self.assertIn("journal_entry_date: \"2025-12-04\"", tuesday_text)

            records = self.parse_jsonl(out)
            by_path = {record["path"]: record for record in records}
            self.assertEqual(by_path[str(monday)]["file_date"], "2025-12-03")
            self.assertEqual(by_path[str(tuesday)]["file_date"], "2025-12-04")

    def test_file_date_requires_year_month_flag_when_path_has_no_year_month(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            monthless = root / "December 2025"
            monthless.mkdir(parents=True)

            note = monthless / "03_monday.md"
            payload = root / "payload.yaml"

            note.write_text("Body\n", encoding="utf-8")
            payload.write_text('journal_entry_date: "{file_date}"\n', encoding="utf-8")

            code_missing, out_missing, err_missing = self.run_cli(
                ["--target", str(monthless), "--payload", str(payload)]
            )
            self.assertEqual(code_missing, 1)
            self.assertEqual(out_missing, "")
            self.assertIn("provide --year-month", err_missing)

            code_apply, out_apply, _ = self.run_cli(
                [
                    "--target",
                    str(monthless),
                    "--payload",
                    str(payload),
                    "--year-month",
                    "2025-12",
                    "--apply",
                ]
            )
            self.assertEqual(code_apply, 0)
            self.assertIn("journal_entry_date: \"2025-12-03\"", note.read_text(encoding="utf-8"))
            records = self.parse_jsonl(out_apply)
            self.assertEqual(records[0]["file_date"], "2025-12-03")


if __name__ == "__main__":
    unittest.main()
