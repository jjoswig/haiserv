"""Unit tests for IServParentLetterSensor entity."""

from __future__ import annotations

import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# HA stub setup (mirrors the pattern from test_sensor.py)
# ---------------------------------------------------------------------------


class _FakeCoordinatorEntity:
    def __init__(self, coordinator):
        self.coordinator = coordinator

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    def __class_getitem__(cls, item):
        return cls


class _FakeSensorEntity:
    pass


class _FakeDataUpdateCoordinator:
    def __init__(self, hass, logger, *, name, update_interval):
        self.hass = hass

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    def __class_getitem__(cls, item):
        return cls


class _FakeUpdateFailed(Exception):
    pass


def _setup_ha_mocks() -> None:
    if "homeassistant" not in sys.modules:
        sys.modules["homeassistant"] = MagicMock()
    if "homeassistant.core" not in sys.modules:
        sys.modules["homeassistant.core"] = MagicMock()
    if "homeassistant.helpers" not in sys.modules:
        sys.modules["homeassistant.helpers"] = MagicMock()

    uc_mod = sys.modules.get("homeassistant.helpers.update_coordinator")
    if uc_mod is None:
        uc_mod = MagicMock()
        sys.modules["homeassistant.helpers.update_coordinator"] = uc_mod
        uc_mod.DataUpdateCoordinator = _FakeDataUpdateCoordinator
        uc_mod.UpdateFailed = _FakeUpdateFailed
    uc_mod.CoordinatorEntity = _FakeCoordinatorEntity

    if "homeassistant.helpers.entity_platform" not in sys.modules:
        sys.modules["homeassistant.helpers.entity_platform"] = MagicMock()
    if "homeassistant.components" not in sys.modules:
        sys.modules["homeassistant.components"] = MagicMock()

    sensor_mod = sys.modules.get("homeassistant.components.sensor")
    if sensor_mod is None:
        sensor_mod = MagicMock()
        sys.modules["homeassistant.components.sensor"] = sensor_mod
    sensor_mod.SensorEntity = _FakeSensorEntity

    if "homeassistant.config_entries" not in sys.modules:
        sys.modules["homeassistant.config_entries"] = MagicMock()


_setup_ha_mocks()

# Force fresh import
for _mod in list(sys.modules):
    if _mod.startswith("custom_components.haiserv.sensor"):
        del sys.modules[_mod]

from custom_components.haiserv.sensor import IServParentLetterSensor  # noqa: E402
from custom_components.haiserv.parentletter_parser import ParentLetter  # noqa: E402
from custom_components.haiserv.const import MAX_CONSECUTIVE_FAILURES  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_LU = "aabbccdd-1111-2222-3333-444455556666"
_CU = "ffffeee0-aaaa-bbbb-cccc-ddddeeee1111"


@pytest.fixture
def sample_letters() -> list[ParentLetter]:
    return [
        ParentLetter(
            letter_uuid=_LU,
            child_uuid=_CU,
            subject="Ausflug",
            sender="Frau Müller",
            child="Max",
            recipient="Klasse 12a",
            created_at=datetime(2024, 3, 15, 9, 30),
            is_unread=True,
        ),
        ParentLetter(
            letter_uuid="00000000-0000-0000-0000-000000000001",
            child_uuid="00000000-0000-0000-0000-000000000002",
            subject="Elternsprechtag",
            sender="Herr Müller",
            child="Erika",
            recipient="Klasse 5b",
            created_at=datetime(2024, 1, 10, 14, 0),
            is_unread=False,
        ),
    ]


@pytest.fixture
def mock_coordinator(sample_letters):
    coordinator = MagicMock()
    coordinator.data = sample_letters
    coordinator.consecutive_failures = 0
    return coordinator


@pytest.fixture
def mock_entry():
    entry = MagicMock()
    entry.entry_id = "test_entry_pl"
    return entry


@pytest.fixture
def sensor(mock_coordinator, mock_entry):
    return IServParentLetterSensor(mock_coordinator, mock_entry)


# ---------------------------------------------------------------------------
# native_value
# ---------------------------------------------------------------------------


class TestParentLetterSensorState:
    def test_one_unread(self, sensor):
        assert sensor.native_value == "1 unread"

    def test_two_unread(self, mock_entry):
        letters = [
            ParentLetter(_LU, _CU, "S1", "A", is_unread=True),
            ParentLetter(_LU, _CU, "S2", "B", is_unread=True),
        ]
        coord = MagicMock()
        coord.data = letters
        coord.consecutive_failures = 0
        s = IServParentLetterSensor(coord, mock_entry)
        assert s.native_value == "2 unread"

    def test_all_read(self, mock_entry):
        letters = [
            ParentLetter(_LU, _CU, "S1", "A", is_unread=False),
        ]
        coord = MagicMock()
        coord.data = letters
        coord.consecutive_failures = 0
        s = IServParentLetterSensor(coord, mock_entry)
        assert s.native_value == "No unread letters"

    def test_empty_list(self, mock_entry):
        coord = MagicMock()
        coord.data = []
        coord.consecutive_failures = 0
        s = IServParentLetterSensor(coord, mock_entry)
        assert s.native_value == "No letters"

    def test_none_data(self, mock_entry):
        coord = MagicMock()
        coord.data = None
        coord.consecutive_failures = 0
        s = IServParentLetterSensor(coord, mock_entry)
        assert s.native_value == "No letters"


# ---------------------------------------------------------------------------
# extra_state_attributes
# ---------------------------------------------------------------------------


class TestParentLetterSensorAttributes:
    def test_letters_key_present(self, sensor, sample_letters):
        attrs = sensor.extra_state_attributes
        assert "letters" in attrs
        assert isinstance(attrs["letters"], list)
        assert len(attrs["letters"]) == len(sample_letters)

    def test_unread_count_correct(self, sensor):
        attrs = sensor.extra_state_attributes
        assert attrs["unread_count"] == 1

    def test_total_count_correct(self, sensor, sample_letters):
        attrs = sensor.extra_state_attributes
        assert attrs["total_count"] == len(sample_letters)

    def test_last_updated_is_iso_string(self, sensor):
        frozen = datetime(2024, 4, 1, 12, 0, 0)
        with patch("custom_components.haiserv.sensor.datetime") as mock_dt:
            mock_dt.now.return_value = frozen
            attrs = sensor.extra_state_attributes
        assert attrs["last_updated"] == frozen.isoformat()

    def test_letter_dict_contains_expected_keys(self, sensor):
        attrs = sensor.extra_state_attributes
        letter_dict = attrs["letters"][0]
        for key in (
            "letter_uuid", "child_uuid", "subject", "sender",
            "additional_senders", "child", "recipient", "created_at", "is_unread",
        ):
            assert key in letter_dict, f"Missing key: {key}"

    def test_body_html_not_in_attributes(self, sensor):
        """body_html is deliberately excluded from attributes to keep size small."""
        attrs = sensor.extra_state_attributes
        for letter_dict in attrs["letters"]:
            assert "body_html" not in letter_dict

    def test_created_at_serialised_as_iso_string(self, sensor):
        attrs = sensor.extra_state_attributes
        created_at = attrs["letters"][0]["created_at"]
        assert created_at == datetime(2024, 3, 15, 9, 30).isoformat()

    def test_created_at_none_serialised_as_none(self, mock_entry):
        letters = [ParentLetter(_LU, _CU, "No date", "X", created_at=None)]
        coord = MagicMock()
        coord.data = letters
        coord.consecutive_failures = 0
        s = IServParentLetterSensor(coord, mock_entry)
        attrs = s.extra_state_attributes
        assert attrs["letters"][0]["created_at"] is None

    def test_empty_letters_attributes(self, mock_entry):
        coord = MagicMock()
        coord.data = []
        coord.consecutive_failures = 0
        s = IServParentLetterSensor(coord, mock_entry)
        attrs = s.extra_state_attributes
        assert attrs["letters"] == []
        assert attrs["unread_count"] == 0
        assert attrs["total_count"] == 0


# ---------------------------------------------------------------------------
# available
# ---------------------------------------------------------------------------


class TestParentLetterSensorAvailability:
    def test_available_no_failures(self, sensor):
        assert sensor.available is True

    def test_available_below_threshold(self, mock_coordinator, mock_entry):
        mock_coordinator.consecutive_failures = MAX_CONSECUTIVE_FAILURES - 1
        s = IServParentLetterSensor(mock_coordinator, mock_entry)
        assert s.available is True

    def test_available_with_data_at_threshold(self, mock_coordinator, mock_entry):
        mock_coordinator.consecutive_failures = MAX_CONSECUTIVE_FAILURES
        s = IServParentLetterSensor(mock_coordinator, mock_entry)
        # data is not empty — sensor should stay available
        assert s.available is True

    def test_unavailable_no_data_at_threshold(self, mock_entry):
        coord = MagicMock()
        coord.data = None
        coord.consecutive_failures = MAX_CONSECUTIVE_FAILURES
        s = IServParentLetterSensor(coord, mock_entry)
        assert s.available is False

    def test_unavailable_empty_data_at_threshold(self, mock_entry):
        coord = MagicMock()
        coord.data = []
        coord.consecutive_failures = MAX_CONSECUTIVE_FAILURES
        s = IServParentLetterSensor(coord, mock_entry)
        assert s.available is False


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


class TestParentLetterSensorIdentity:
    def test_unique_id(self, sensor, mock_entry):
        assert sensor._attr_unique_id == f"{mock_entry.entry_id}_parentletter"

    def test_name(self, sensor):
        assert sensor._attr_name == "iServ Parent Letters"
