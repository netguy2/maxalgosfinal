import dotenv
import os
dotenv.load_dotenv()

# Print DB config
print("DATABASE_URL:", os.getenv("DATABASE_URL"))

from database.deployment_db import Deployment
from database.symbol import _get_active_model_and_session
m, s = _get_active_model_and_session()

try:
    count = s.query(Deployment).count()
    print("Deployments count:", count)
    for d in s.query(Deployment).all():
        print(f"ID: {d.id}, Name: {d.name}, User ID: {d.user_id}, Broker: {d.broker}, Status: {d.status}")
except Exception as e:
    print("Error querying Deployments:", e)
