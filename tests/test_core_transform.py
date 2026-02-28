import re
import unittest

try:
    from yaml_injektr.core import normalize_payload_text, transform_markdown
except ModuleNotFoundError as exc:
    if getattr(exc, "name", None) == "yaml_injektr":
        raise ModuleNotFoundError(
            "yaml_injektr is not installed. Run: python -m pip install -e .  (or: python -m pip install .)"
        ) from exc
    raise


class TransformMarkdownTests(unittest.TestCase):
    def test_preserves_existing_uuid_and_replaces_other_frontmatter(self) -> None:
        text = """---
uuid: keep-me
title: old
kind: note
---
Body text\n"""
        payload = "title: new\nuuid: override\nstatus: active\n"

        new_text, info = transform_markdown(text, payload)

        self.assertIn("title: new\n", new_text)
        self.assertIn("uuid: keep-me\n", new_text)
        self.assertIn("status: active\n", new_text)
        self.assertNotIn("title: old", new_text)
        self.assertNotIn("kind: note", new_text)
        self.assertTrue(info["had_frontmatter"])
        self.assertTrue(info["preserved_uuid"])
        self.assertFalse(info["generated_uuid"])
        self.assertFalse(info["error"])

    def test_inserts_frontmatter_when_missing_without_adding_uuid(self) -> None:
        text = "# Heading\n\nNo front matter.\n"
        payload = "title: Fresh\ntags:\n  - a\n"

        new_text, info = transform_markdown(text, payload)

        self.assertTrue(new_text.startswith("---\ntitle: Fresh\n"))
        self.assertNotIn("\nuuid:", new_text)
        self.assertTrue(new_text.endswith(text))
        self.assertFalse(info["had_frontmatter"])
        self.assertFalse(info["preserved_uuid"])
        self.assertFalse(info["generated_uuid"])

    def test_generates_uuidv7_when_payload_has_token_and_no_existing_uuid(self) -> None:
        text = "Body\n"
        payload = "uuid: \"{uuidv7}\"\ntitle: generated\n"

        new_text, info = transform_markdown(text, payload)

        self.assertTrue(info["generated_uuid"])
        self.assertFalse(info["preserved_uuid"])
        match = re.search(r"^uuid\s*:\s*([0-9a-f\-]{36})$", new_text, re.MULTILINE)
        self.assertIsNotNone(match)
        self.assertNotIn("{uuidv7}", new_text)

    def test_existing_uuid_wins_over_payload_value_or_token(self) -> None:
        text = """---
uuid: existing-123
---
Body\n"""
        payload = "uuid: {uuidv7}\ntitle: keep\n"

        new_text, info = transform_markdown(text, payload)

        self.assertIn("uuid: existing-123\n", new_text)
        self.assertTrue(info["preserved_uuid"])
        self.assertFalse(info["generated_uuid"])

    def test_bom_at_start_is_tolerated_and_not_written_back(self) -> None:
        text = "\ufeff---\nuuid: bom-uuid\n---\nBody\n"
        payload = "title: after\n"

        new_text, info = transform_markdown(text, payload)

        self.assertFalse(new_text.startswith("\ufeff"))
        self.assertIn("uuid: bom-uuid\n", new_text)
        self.assertTrue(info["had_frontmatter"])

    def test_missing_frontmatter_closer_is_error_and_unchanged(self) -> None:
        text = "---\nuuid: bad\nno close"
        payload = "title: nope\n"

        new_text, info = transform_markdown(text, payload)

        self.assertEqual(new_text, text)
        self.assertTrue(info["error"])
        self.assertIn("no closing marker", str(info["reason"]))

    def test_preserves_crlf_newlines(self) -> None:
        text = "---\r\nuuid: abc\r\n---\r\nLine1\r\n---\r\nLine2\r\n"
        payload = "title: crlf\n"

        new_text, _ = transform_markdown(text, payload)

        self.assertIsNone(re.search(r"(?<!\r)\n", new_text))
        self.assertIn("Line1\r\n---\r\nLine2\r\n", new_text)

    def test_body_delimiter_later_is_not_treated_as_frontmatter(self) -> None:
        text = "Intro\n---\nNot front matter\n"
        payload = "title: inserted\n"

        new_text, info = transform_markdown(text, payload)

        self.assertFalse(info["had_frontmatter"])
        self.assertTrue(new_text.endswith(text))

    def test_payload_wrapped_block_is_accepted(self) -> None:
        text = "Body\n"
        payload = "---\ntitle: wrapped\n---\n"

        new_text, _ = transform_markdown(text, payload)

        self.assertIn("title: wrapped\n", new_text)

    def test_payload_wrapper_without_closer_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            normalize_payload_text("---\ntitle: bad\n")

    def test_uuid_detection_is_column_zero_only(self) -> None:
        text = "Body\n"
        payload = "meta:\n  uuid: {uuidv7}\nname: nested\n"

        new_text, info = transform_markdown(text, payload)

        self.assertFalse(info["generated_uuid"])
        self.assertIn("  uuid: {uuidv7}", new_text)


if __name__ == "__main__":
    unittest.main()
