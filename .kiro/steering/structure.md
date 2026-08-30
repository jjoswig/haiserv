# Project Structure

```
haiserv/
├── custom_components/
│   └── haiserv/              # Main integration package
│       ├── __init__.py       # Entry point: async_setup_entry / async_unload_entry
│       ├── api.py            # IServClient: authentication + timetable fetching
│       ├── config_flow.py    # UI config flow (URL, username, password)
│       ├── const.py          # Constants: DOMAIN, timeouts, intervals, DAY_ORDER
│       ├── coordinator.py    # DataUpdateCoordinator: polling + error recovery
│       ├── manifest.json     # HA integration metadata (domain, version, requirements)
│       ├── parser.py         # Lesson dataclass, parse/sort/format logic
│       ├── sensor.py         # IServTimetableSensor entity
│       └── strings.json      # UI strings for config flow
├── tests/
│   ├── conftest.py           # Shared fixtures + HA module mocking
│   ├── test_api.py           # API client tests
│   ├── test_config_flow.py   # Config flow tests
│   ├── test_coordinator.py   # Coordinator tests
│   ├── test_sensor.py        # Sensor entity tests
│   ├── test_strings.py       # strings.json validation
│   ├── test_*_properties.py  # Hypothesis property-based tests
│   └── test_integration.py   # End-to-end integration tests
├── pytest.ini                # Pytest configuration
└── .hypothesis/              # Hypothesis test database (auto-generated)
```

## Architecture

The integration follows the standard Home Assistant custom component pattern:

1. **Config Flow** (`config_flow.py`) — validates credentials and creates a config entry
2. **Setup** (`__init__.py`) — creates `IServClient` and `IServCoordinator`, forwards to sensor platform
3. **API Client** (`api.py`) — handles HTTP auth and data fetching with retry on session expiry
4. **Coordinator** (`coordinator.py`) — polls on interval, handles errors, stores parsed data
5. **Parser** (`parser.py`) — transforms raw JSON into `Lesson` dataclass instances
6. **Sensor** (`sensor.py`) — exposes timetable as HA entity with state + attributes

## Conventions

- One module per concern (api, parser, coordinator, sensor, config_flow, const)
- All async I/O uses `async`/`await` — no blocking calls
- Google-style docstrings with `Args:`, `Returns:`, `Raises:` sections
- Full type annotations on all function signatures
- Custom exceptions (`AuthenticationError`, `CannotConnect`) defined in `api.py`
- Constants live in `const.py` and are imported where needed
- Tests mock Home Assistant entirely via `conftest.py` — no HA install required
