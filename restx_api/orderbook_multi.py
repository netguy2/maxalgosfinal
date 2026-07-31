import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from marshmallow import ValidationError

from limiter import limiter
from services.orderbook_service import get_orderbook_multi
from utils.logging import get_logger

from .account_schema import OrderbookSchema

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace(
    "orderbook_multi",
    description="Merged order book across every connected broker",
)

logger = get_logger(__name__)

orderbook_schema = OrderbookSchema()


@api.route("/", strict_slashes=False)
class OrderbookMulti(Resource):
    """Additive sibling of /orderbook: same {"apikey": ...} payload, but
    returns orders merged across every CONNECTED broker (not just the data
    broker), each tagged with its own `broker` field. The original
    /orderbook endpoint and single-broker orderbook behavior are
    untouched."""

    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        try:
            data = orderbook_schema.load(request.json)
            api_key = data["apikey"]

            success, response_data, status_code = get_orderbook_multi(api_key=api_key)

            return make_response(jsonify(response_data), status_code)

        except ValidationError as err:
            return make_response(jsonify({"status": "error", "message": err.messages}), 400)
        except Exception:
            logger.exception("An unexpected error occurred in OrderbookMulti endpoint.")
            return make_response(
                jsonify({"status": "error", "message": "An unexpected error occurred"}), 500
            )
