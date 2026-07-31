# Mapping Max Algos API Request https://maxalgos.in/docs
# Bnr does not provide position-specific Margin Calculator API

from utils.logging import get_logger

logger = get_logger(__name__)


def transform_margin_positions(positions):
    """
    Transform Max Algos margin position format to broker format.

    Note: Bnr does not provide a position-specific margin calculator API.
    The available Margin API only returns account-level margin information.

    Args:
        positions: List of positions in Max Algos format

    Raises:
        NotImplementedError: Bnr does not support position-specific margin calculator API
    """
    raise NotImplementedError("Bnr does not support position-specific margin calculator API")


def parse_margin_response(response_data):
    """
    Parse broker margin calculator response to Max Algos standard format.

    Note: Bnr does not provide a position-specific margin calculator API.
    The available Margin API only returns account-level margin information.

    Args:
        response_data: Raw response from broker margin calculator API

    Raises:
        NotImplementedError: Bnr does not support position-specific margin calculator API
    """
    raise NotImplementedError("Bnr does not support position-specific margin calculator API")
