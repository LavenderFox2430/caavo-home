"""Constants for the local Caavo Home API."""

DOMAIN = "caavo_home"
DEFAULT_PORT = 8090
API_PATH = "/api/v1"
CONF_TOKEN = "token"
POLL_INTERVAL = 10
GET_TIMEOUT = 10
POST_TIMEOUT = 25
COMMAND_INTERVAL = 0.12
MAX_RESPONSE_BYTES = 65536
KEYS = frozenset(
    {
        "up",
        "down",
        "left",
        "right",
        "select",
        "back",
        "menu",
        "caavo",
        "home",
        "volume_up",
        "volume_down",
        "mute",
        "play_pause",
        "rewind",
        "forward",
        "page_up",
        "page_down",
        "keypad",
        *(f"num_{number}" for number in range(10)),
    }
)
POWER_STATES = ("on", "off", "transitioning", "unknown")
SIGNAL_STATES = ("connected", "standby", "disconnected", "unknown")
