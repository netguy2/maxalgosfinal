import os

from flask import jsonify, make_response, request
from flask_restx import Namespace, Resource
from marshmallow import ValidationError

from limiter import limiter
from restx_api.schemas import BasketOrderSchema
from services.multi_broker_order_service import place_basket_order_multi
from utils.logging import get_logger

API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "10 per second")
api = Namespace(
    "basket_order_multi",
    description="Fan a basket order out to several connected brokers sequentially",
)

logger = get_logger(__name__)

basket_schema = BasketOrderSchema()


@api.route("/", strict_slashes=False)
class BasketOrderMulti(Resource):
    """Additive sibling of /basketorder: same payload shape, plus a required
    `brokers` list. Placed sequentially per broker via
    services.multi_broker_order_service.place_basket_order_multi, which
    reuses the existing, unmodified process_basket_order_with_auth per
    broker. The original /basketorder endpoint and single-broker basket
    flow are untouched."""

    @limiter.limit(API_RATE_LIMIT)
    def post(self):
        try:
            data = request.json or {}
            brokers = data.get("brokers")

            try:
                basket_data = basket_schema.load(
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

            api_key = basket_data.pop("apikey", None)

            success, response_data, status_code = place_basket_order_multi(
                basket_data=basket_data, api_key=api_key, brokers=brokers
            )

            return make_response(jsonify(response_data), status_code)

        except Exception:
            logger.exception("An unexpected error occurred in BasketOrderMulti endpoint.")
            return make_response(
                jsonify({"status": "error", "message": "An unexpected error occurred"}), 500
            )
