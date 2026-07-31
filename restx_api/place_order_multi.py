import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from marshmallow import ValidationError

from limiter import limiter
from restx_api.schemas import OrderSchema
from services.multi_broker_order_service import place_order_multi
from utils.logging import get_logger

ORDER_RATE_LIMIT = os.getenv("ORDER_RATE_LIMIT", "10 per second")
api = Namespace(
    "place_order_multi",
    description="Fan a single order out to several connected brokers sequentially",
)

logger = get_logger(__name__)

order_schema = OrderSchema()


@api.route("/", strict_slashes=False)
class PlaceOrderMulti(Resource):
    """Additive sibling of /placeorder: same payload shape, plus a required
    `brokers` list. Placed sequentially per broker via
    services.multi_broker_order_service.place_order_multi, which reuses the
    existing, unmodified place_order per broker. The original /placeorder
    endpoint and single-broker order flow are untouched."""

    @limiter.limit(ORDER_RATE_LIMIT)
    def post(self):
        try:
            data = request.json or {}
            brokers = data.get("brokers")

            try:
                order_data = order_schema.load(
                    {k: v for k, v in data.items() if k != "brokers"}
                )
            except ValidationError as err:
                return make_response(
                    jsonify({"status": "error", "message": str(err.messages)}), 400
                )

            if not brokers or not isinstance(brokers, list):
                return make_response(
                    jsonify({"status": "error", "message": "brokers (list) is required"}), 400
                )

            api_key = order_data.pop("apikey", None)

            success, response_data, status_code = place_order_multi(
                order_data=order_data, api_key=api_key, brokers=brokers
            )

            return make_response(jsonify(response_data), status_code)

        except Exception:
            logger.exception("An unexpected error occurred in PlaceOrderMulti endpoint.")
            return make_response(
                jsonify({"status": "error", "message": "An unexpected error occurred"}), 500
            )
