"""Shared test configuration and fixtures for iServ integration tests.

Mocks the homeassistant package to allow importing custom_components.iserv
modules without requiring a full Home Assistant installation.
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock the homeassistant package and its submodules so that
# custom_components.iserv can be imported without Home Assistant installed.
HOMEASSISTANT_MODULES = [
    "homeassistant",
    "homeassistant.config_entries",
    "homeassistant.core",
    "homeassistant.data_entry_flow",
    "homeassistant.helpers",
    "homeassistant.helpers.aiohttp_client",
    "homeassistant.helpers.update_coordinator",
    "homeassistant.helpers.entity_platform",
    "homeassistant.components",
    "homeassistant.components.sensor",
]

for mod in HOMEASSISTANT_MODULES:
    if mod not in sys.modules:
        mock_mod = MagicMock()
        # Mark parent modules as packages so Python resolves submodule imports
        if any(m.startswith(mod + ".") for m in HOMEASSISTANT_MODULES):
            mock_mod.__path__ = []
            mock_mod.__package__ = mod
        sys.modules[mod] = mock_mod

# Ensure the top-level 'homeassistant' mock is treated as a package
ha_mock = sys.modules["homeassistant"]
ha_mock.__path__ = []
ha_mock.__package__ = "homeassistant"
# Wire up sub-module attributes so 'from homeassistant import X' works
ha_mock.config_entries = sys.modules["homeassistant.config_entries"]
ha_mock.data_entry_flow = sys.modules["homeassistant.data_entry_flow"]
ha_mock.core = sys.modules["homeassistant.core"]
ha_mock.helpers = sys.modules["homeassistant.helpers"]
ha_mock.components = sys.modules["homeassistant.components"]

# Wire up helpers sub-modules
helpers_mock = sys.modules["homeassistant.helpers"]
helpers_mock.__path__ = []
helpers_mock.__package__ = "homeassistant.helpers"
helpers_mock.aiohttp_client = sys.modules["homeassistant.helpers.aiohttp_client"]
helpers_mock.update_coordinator = sys.modules["homeassistant.helpers.update_coordinator"]
helpers_mock.entity_platform = sys.modules["homeassistant.helpers.entity_platform"]

# Wire up components sub-modules
components_mock = sys.modules["homeassistant.components"]
components_mock.__path__ = []
components_mock.__package__ = "homeassistant.components"
components_mock.sensor = sys.modules["homeassistant.components.sensor"]


# --- Shared Fixtures ---


@pytest.fixture
def mock_iserv_client():
    """Create a mocked IServClient with AsyncMock methods.

    Returns a MagicMock that simulates the IServClient interface:
    - authenticate() -> AsyncMock returning True
    - fetch_timetable() -> AsyncMock returning empty JSON list '[]'
    - is_authenticated -> True
    """
    client = MagicMock()
    client.authenticate = AsyncMock(return_value=True)
    client.fetch_timetable = AsyncMock(return_value="[]")
    client.is_authenticated = True
    client._base_url = "https://school.iserv.de"
    client._username = "testuser"
    client._password = "testpass"
    return client


@pytest.fixture
def sample_lessons():
    """Create a list of sample Lesson objects for use across tests.

    Returns 5 lessons spanning Monday through Friday with realistic data.
    """
    from custom_components.iserv.parser import Lesson

    return [
        Lesson(
            day="Monday",
            start_time="08:00",
            end_time="08:45",
            subject="Mathematics",
            room="A101",
        ),
        Lesson(
            day="Monday",
            start_time="09:00",
            end_time="09:45",
            subject="English",
            room="B202",
        ),
        Lesson(
            day="Tuesday",
            start_time="10:00",
            end_time="10:45",
            subject="Physics",
            room="C303",
        ),
        Lesson(
            day="Wednesday",
            start_time="08:00",
            end_time="08:45",
            subject="History",
            room="D404",
        ),
        Lesson(
            day="Friday",
            start_time="14:00",
            end_time="14:45",
            subject="Art",
            room="E505",
        ),
    ]


@pytest.fixture
def mock_aiohttp_session():
    """Create a MagicMock for aiohttp.ClientSession.

    Returns a MagicMock with async context manager support for
    get() and post() methods, simulating aiohttp responses.
    """
    session = MagicMock()

    # Create a mock response
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.text = AsyncMock(return_value="[]")
    mock_response.raise_for_status = MagicMock()
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    # Make session.get() and session.post() return async context managers
    session.get = MagicMock(return_value=mock_response)
    session.post = MagicMock(return_value=mock_response)

    return session


@pytest.fixture
def mock_coordinator(sample_lessons):
    """Create a mocked coordinator with data and consecutive_failures.

    Returns a MagicMock simulating the IServCoordinator with:
    - data: the sample_lessons list
    - consecutive_failures: 0
    - last_update_success: True
    """
    from custom_components.iserv.const import MAX_CONSECUTIVE_FAILURES

    coordinator = MagicMock()
    coordinator.data = sample_lessons
    coordinator.consecutive_failures = 0
    coordinator.last_update_success = True

    # Add an available property that mirrors real coordinator logic
    type(coordinator).available = property(
        lambda self: self.consecutive_failures < MAX_CONSECUTIVE_FAILURES
    )

    return coordinator
