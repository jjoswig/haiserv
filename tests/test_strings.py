"""Tests validating strings.json structure for the HAiServ integration."""

import json
from pathlib import Path

import pytest

STRINGS_PATH = Path(__file__).parent.parent / "custom_components" / "haiserv" / "strings.json"


class TestStringsJsonStructure:
    """Validate the localization strings structure."""

    @pytest.fixture(autouse=True)
    def load_strings(self):
        """Load strings.json once for all tests."""
        with open(STRINGS_PATH, encoding="utf-8") as f:
            self.strings = json.load(f)

    def test_description_exists_and_has_two_paragraphs(self):
        """Description should contain two paragraphs separated by \\n\\n.

        Validates: Requirements 1.1, 1.2, 1.3, 1.4
        """
        description = self.strings["config"]["step"]["user"]["description"]
        paragraphs = description.split("\n\n")
        assert len(paragraphs) == 2
        # First paragraph: welcome + what HAiServ does
        assert "HAiServ" in paragraphs[0]
        assert "iServ" in paragraphs[0]
        # Second paragraph: iServ account requirement
        assert "iServ" in paragraphs[1]
        assert "account" in paragraphs[1].lower()

    def test_url_label_is_correct(self):
        """URL field label should be 'URL'.

        Validates: Requirements 2.1
        """
        assert self.strings["config"]["step"]["user"]["data"]["url"] == "URL"

    def test_username_label_is_correct(self):
        """Username field label should be 'Username'.

        Validates: Requirements 2.2
        """
        assert self.strings["config"]["step"]["user"]["data"]["username"] == "Username"

    def test_password_label_is_correct(self):
        """Password field label should be 'Password'.

        Validates: Requirements 2.3, 2.4
        """
        assert self.strings["config"]["step"]["user"]["data"]["password"] == "Password"

    def test_create_entry_message_exists_and_has_url_placeholder(self):
        """create_entry.default should exist and contain {url} placeholder.

        Validates: Requirements 3.1, 3.2
        """
        message = self.strings["config"]["create_entry"]["default"]
        assert "{url}" in message
