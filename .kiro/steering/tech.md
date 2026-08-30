# Tech Stack & Build

## Language

- Python 3 (uses `from __future__ import annotations` throughout)

## Framework

- Home Assistant custom component (HACS-compatible structure)
- Follows HA patterns: `ConfigEntry`, `DataUpdateCoordinator`, `CoordinatorEntity`, `SensorEntity`

## Key Libraries

- `aiohttp` — async HTTP client for iServ communication
- `voluptuous` — schema validation for config flow user input
- `dataclasses` — domain model (`Lesson` dataclass)
- `asyncio` — async/await throughout

## Testing

- `pytest` with `asyncio_mode = auto` (no manual `@pytest.mark.asyncio` needed)
- `hypothesis` — property-based testing for parser and URL validation
- `unittest.mock` — `MagicMock` / `AsyncMock` for HA and aiohttp stubs
- Home Assistant is fully mocked in `conftest.py` (no HA installation required to run tests)

## Project Configuration

- `manifest.json` — declares domain, version, requirements, and IoT class per HA custom component convention
- `pytest.ini` — test runner config (`testpaths = tests`)
- No `pyproject.toml`, `setup.py`, or `requirements.txt` — dependencies are declared in `manifest.json` only

## Common Commands

```bash
# Run all tests
pytest

# Run a specific test file
pytest tests/test_parser_properties.py

# Run tests with verbose output
pytest -v
```
