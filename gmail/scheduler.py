import logging
import time

import schedule
import yaml

from gmail.auth import get_credentials
from gmail.client import build_service
from gmail.actions import run_cleanup

logging.basicConfig(
    filename="gmail_graveyard.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def _load_config():
    with open("config.yaml") as f:
        return yaml.safe_load(f)


def _scheduled_run():
    logging.info("Starting scheduled cleanup run")
    try:
        config = _load_config()
        creds = get_credentials()
        service = build_service(creds)
        run_cleanup(service, config, dry_run=False)
        logging.info("Scheduled cleanup complete")
    except Exception as e:
        logging.error(f"Scheduled run failed: {e}")


def start_scheduler(config):
    sched = config.get("automation", {}).get("schedule", "daily")
    print(f"Gmail Graveyard scheduler started ({sched} at 09:00).")
    print("Logs written to gmail_graveyard.log")
    print("Press Ctrl+C to stop.\n")

    if sched == "weekly":
        schedule.every().monday.at("09:00").do(_scheduled_run)
    else:
        schedule.every().day.at("09:00").do(_scheduled_run)

    while True:
        schedule.run_pending()
        time.sleep(60)
