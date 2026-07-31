import os
import sys

# Add root folder to python path
sys.path.append(os.getcwd())

from utils.logging import get_logger
import logging

# Set logging level to debug to see all zebu downloads
logging.basicConfig(level=logging.DEBUG)

from broker.zebu.database.master_contract_db import master_contract_download

print("Starting Zebu Master Contract Download test...")
try:
    res = master_contract_download()
    print("Download finished. Result:", res)
except Exception as e:
    print("Exception during download:", e)
