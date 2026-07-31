"""Base event with common fields shared by all order events."""

from dataclasses import dataclass, field

from utils.event_bus import Event


@dataclass
class OrderEvent(Event):
    """
    Base for all order-related events.

    Every order event carries:
    - mode: "live" or "analyze" — subscribers branch on this
    - api_type: the operation name used for logging and telegram templates
    - request_data / response_data: dicts for log subscribers
    - api_key: for telegram username resolution
    - username: set directly by internal call paths (auth_token+broker,
      e.g. signal_engine.py's webhook/deployment order placement) that have
      no Max Algos api_key to resolve a username from. Room-scoping
      subscribers (socketio_subscriber.py) fall back to this when api_key
      is empty, so those orders' status still reaches the owning user
      instead of being silently dropped.
    """

    mode: str = "live"  # "live" or "analyze"
    api_type: str = ""
    request_data: dict = field(default_factory=dict)
    response_data: dict = field(default_factory=dict)
    api_key: str = ""
    username: str = ""
