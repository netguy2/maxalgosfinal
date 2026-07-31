import logging
import os

from sqlalchemy import Column, Float, Integer, String, Sequence, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.sql import func

from database.engine_factory import create_db_engine

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_db_engine(DATABASE_URL)

db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()


class Instrument(Base):
    """Universal Instrument Model covering all asset classes"""

    __tablename__ = "instruments"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(255), nullable=False, index=True)
    brsymbol = Column(String(255), nullable=False, index=True)
    name = Column(String(255), index=True)
    exchange = Column(String(50), nullable=False, index=True)
    segment = Column(String(50), nullable=False)
    token = Column(String(100), nullable=False, index=True)
    expiry = Column(String(50), nullable=True)
    strike = Column(Float, nullable=True)
    option_type = Column(String(10), nullable=True)
    lotsize = Column(Integer, default=1)
    tick_size = Column(Float, default=0.05)
    multiplier = Column(Float, default=1.0)
    asset_class = Column(String(50), nullable=False, default="Equity")  # Equity, Futures, Options, Index, ETF, Currency, Commodity
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def to_dict(self):
        return {
            "id": self.id,
            "symbol": self.symbol,
            "brsymbol": self.brsymbol,
            "name": self.name,
            "exchange": self.exchange,
            "segment": self.segment,
            "token": self.token,
            "expiry": self.expiry,
            "strike": self.strike,
            "option_type": self.option_type,
            "lotsize": self.lotsize,
            "tick_size": self.tick_size,
            "multiplier": self.multiplier,
            "asset_class": self.asset_class,
        }


def init_db():
    """Initialize the Instrument Registry database tables"""
    from database.db_init_helper import init_db_with_logging
    init_db_with_logging(Base, engine, "Instrument Registry DB", logger)


def register_instrument(instrument_data: dict) -> Instrument:
    """Register or update an instrument record in the registry"""
    try:
        symbol = instrument_data["symbol"]
        exchange = instrument_data["exchange"]
        
        # Check if already registered
        inst = Instrument.query.filter_by(symbol=symbol, exchange=exchange).first()
        if not inst:
            inst = Instrument(**instrument_data)
            db_session.add(inst)
        else:
            for key, val in instrument_data.items():
                setattr(inst, key, val)
        db_session.commit()
        return inst
    except Exception as e:
        logger.exception(f"Error registering instrument: {e}")
        db_session.rollback()
        return None


def get_instrument_by_symbol(symbol: str, exchange: str) -> Instrument:
    """Fetch an instrument by its symbol and exchange"""
    try:
        return Instrument.query.filter_by(symbol=symbol, exchange=exchange).first()
    except Exception as e:
        logger.error(f"Error fetching instrument: {e}")
        return None
