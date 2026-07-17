"""Constants for the iServ integration."""

DOMAIN = "haiserv"

# Update interval in minutes
DEFAULT_UPDATE_INTERVAL = 60

# Connection timeout in seconds
CONNECTION_TIMEOUT = 10

# Request timeout in seconds
REQUEST_TIMEOUT = 30

# Number of consecutive failures before marking entity unavailable
MAX_CONSECUTIVE_FAILURES = 3

# Day ordering for sorting lessons (Monday through Friday)
DAY_ORDER = {
    "Monday": 0,
    "Tuesday": 1,
    "Wednesday": 2,
    "Thursday": 3,
    "Friday": 4,
}
