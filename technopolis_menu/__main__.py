import json
import logging
import os
import re
import typing
from datetime import datetime, timedelta

import httpx
import pytz

from .config import DUMMY  # isort: split
from .extractor import DAYS, parse_menu_gpt, parse_menu_simple
from .s3 import get_s3_resource
from .slack import run_slack_post
from .stats import get_all, incr_stat

if typing.TYPE_CHECKING:
    # Reference DUMMY to avoid unused import warning/removal
    DUMMY

# Log to stdout
logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)

PARSE_APPLICATION_ID = os.environ.get("PARSE_APPLICATION_ID")
PARSE_CLIENT_KEY = os.environ.get("PARSE_CLIENT_KEY")
PARSE_INSTALLATION_ID = os.environ.get("PARSE_INSTALLATION_ID")

SLACK_POST_TIME = os.environ.get("SLACK_POST_TIME", "10:00")
SLACK_POST_TZ = os.environ.get("SLACK_POST_TZ", "Europe/Oslo")
# How many minutes before or after SLACK_POST_TIME should we post?
# Too low and we might miss the window, too high and we might post twice.
SLACK_POST_WINDOW = int(os.environ.get("SLACK_POST_WINDOW", "15"))

PUBLIC_BUCKET = os.environ.get("PUBLIC_BUCKET", None)


PARSE_HEADERS = {
    "User-Agent": "Parse Android SDK API Level 33",
    "X-Parse-App-Build-Version": "152",
    "X-Parse-App-Display-Version": "1.11.2",
    "X-Parse-Os-Version": "13",
    "X-Parse-Application-Id": PARSE_APPLICATION_ID,
    "X-Parse-Client-Key": PARSE_CLIENT_KEY,
    "X-Parse-Installation-Id": PARSE_INSTALLATION_ID,
}


def parse_melding(start_date: datetime, end_date: datetime):
    url = "https://technopolis1.herokuapp.com/parse/classes/Melding"
    payload = {
        "limit": "100",
        "where": {
            "gyldig_til": {"$gte": {"__type": "Date", "iso": end_date.isoformat()}},
            "$or": [
                {"publisert": True},
                {
                    "publisertFraDatoTid": {"$lte": {"__type": "Date", "iso": start_date.isoformat()}},
                    "publisert": False,
                    "publisertStatus": {"$in": ["2", "3"]},
                },
            ],
        },
        "order": "-publishedAt",
        "_method": "GET",
    }
    response = httpx.post(url, headers=PARSE_HEADERS, json=payload)
    logger.info(f"Got {response.status_code} from parse")
    response.raise_for_status()
    return response.json()


MENU_TEXT_REGEX = re.compile(r"Meny uke (?P<week>\d+), (?P<cantina>Expedisjon|Transit) \d\.etg")


def get_menu_messages(messages):
    result = {}
    for message in messages:
        if m := MENU_TEXT_REGEX.match(message["tekst"]):
            cantina = m.group("cantina").lower()
            if cantina not in result:
                result[cantina] = message
    return result


def extract_menu(message):
    result = {
        "title": message["tekst"],
        "raw_description": message["langBeskrivelse"],
        # Note publishedAt is {__type: "Date"}, while createdAt and updatedAt are strings
        "published_at": message["publishedAt"]["iso"],
        "created_at": message["createdAt"],
        "updated_at": message["updatedAt"],
    }
    try:
        result["gpt"] = parse_menu_gpt(message["langBeskrivelse"])
    except Exception:
        logger.exception("Failed to parse menu with openai")
    result["simple"] = parse_menu_simple(message["langBeskrivelse"])
    return result


def should_post_to_slack() -> bool:
    """
    Check if we should post to slack on this run.
    Returns true if it's a weekday, and the current time is +- 10 minutes of SLACK_POST_TIME (corrected for SLACK_POST_TZ)
    :return: True if we should post to slack
    """
    local_time = datetime.now(pytz.timezone(SLACK_POST_TZ))
    if local_time.weekday() > 4:
        return False

    post_time = datetime.strptime(SLACK_POST_TIME, "%H:%M").time()
    total_minutes = local_time.hour * 60 + local_time.minute
    post_minutes = post_time.hour * 60 + post_time.minute

    return abs(total_minutes - post_minutes) < SLACK_POST_WINDOW


def upload_to_s3(menus: dict):
    """
    Uploads menus to /menu/{week}.json, and the path of the file to /menu/latest
    :param menus:
    :return:

    TODO: Fetch latest menu from s3, and only upload if it's different?
    """

    s3 = get_s3_resource()
    bucket = s3.Bucket(PUBLIC_BUCKET)
    week = datetime.now().isocalendar()[1]
    key = f"menu/{week}.json"
    logger.debug(f"Uploading menu to {key}", extra={"menus": menus})
    bucket.Object(key).put(
        Body=json.dumps(menus).encode("utf-8"),
        ContentType="application/json",
        ACL="public-read",
    )
    bucket.Object(
        "menu/latest",
    ).put(Body=str(key).encode("utf-8"), ContentType="text/plain", ACL="public-read")

    logger.info(f"Uploaded menu to {key}")
    incr_stat("upload_menu")


def main():
    # Try to get messages for the past week
    start_date = datetime.now()
    # app appears to set this to 23:00 yesterday, not sure why but let's do the same
    end_date = start_date - timedelta(days=1)
    end_date = end_date.replace(hour=23, minute=0, second=0, microsecond=0)

    # Get messages
    if test_file := os.environ.get("TEST_FILE", None):
        with open(test_file, "r") as f:
            messages = json.load(f)
    else:
        messages = parse_melding(start_date, end_date)

    # TODO: Add flag to trigger this
    if not test_file:
        with open("test.json", "w") as f:
            json.dump(messages, f)

    cantinas = get_menu_messages(messages["results"])

    # Extract menu
    menus = {name: extract_menu(message) for name, message in cantinas.items()}

    logger.debug(f"Menu: {menus}")

    if PUBLIC_BUCKET:
        upload_to_s3(menus)

    # Find today's menu
    today = datetime.now().weekday()
    if today > 4:
        return
    today = DAYS[today]

    # Print menu
    for name in ("transit", "expedisjon"):
        if name not in menus:
            print(f"No menu for {name}")
            continue
        print(f"{name.capitalize()} {today.capitalize()}")
        parsed_menu = menus[name]["simple"]
        if "gpt" in menus[name]:
            parsed_menu = menus[name]["gpt"]
        for item in parsed_menu[today]:
            print(f" - {item}")
    if any("gpt" in m for m in menus.values()):
        print("Powered by OpenAI GPT-3.5 Turbo")

    if "transit" not in menus and "expedisjon" not in menus:
        logger.warning("No menu found, skipping")
        return

    if should_post_to_slack():
        run_slack_post(today, menus)

    logger.info(f"stats: {get_all()}")


if __name__ == "__main__":
    main()
