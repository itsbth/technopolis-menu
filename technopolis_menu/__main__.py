import logging
import os
import re
from datetime import datetime, timedelta

import httpx
from dotenv import load_dotenv

from .extractor import DAYS, parse_menu_gpt, parse_menu_simple

load_dotenv()
load_dotenv(".env.local")

# Log to stdout
logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)

SLACK_HOOK = os.environ.get("SLACK_HOOK", None)

PARSE_APPLICATION_ID = os.environ.get("PARSE_APPLICATION_ID")
PARSE_CLIENT_KEY = os.environ.get("PARSE_CLIENT_KEY")
PARSE_INSTALLATION_ID = os.environ.get("PARSE_INSTALLATION_ID")

PARSE_HEADERS = {
    "User-Agent": "Parse Android SDK API Level 33",
    "X-Parse-App-Build-Version": "152",
    "X-Parse-App-Display-Version": "1.11.2",
    "X-Parse-Application-Id": PARSE_APPLICATION_ID,
    "X-Parse-Client-Key": PARSE_CLIENT_KEY,
    "X-Parse-Installation-Id": PARSE_INSTALLATION_ID,
    "X-Parse-Os-Version": "13",
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
                    "publisertFraDatoTid": {
                        "$lte": {"__type": "Date", "iso": start_date.isoformat()}
                    },
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


MENU_TEXT_REGEX = re.compile(
    r"Meny uke (?P<week>\d+), (?P<cantina>Expedisjon|Transit) \d\.etg"
)


def extract_menu(messages):
    result = {}
    # Store if any lists are (successfully) parsed by openai, se we can add a "Powered by AI" footer
    openai_parsed = False
    for message in messages:
        if m := MENU_TEXT_REGEX.match(message["tekst"]):
            cantina = m.group("cantina").lower()
            if cantina not in result:
                result[cantina] = {}
            if "langBeskrivelse" in message:
                try:
                    result[cantina] = parse_menu_gpt(message["langBeskrivelse"])
                    openai_parsed = True
                except Exception:
                    import traceback

                    traceback.print_exc()
                    result[cantina] = parse_menu_simple(message["langBeskrivelse"])
    return result, openai_parsed


def create_slack_message(menu: dict, today: datetime, openai_parsed: bool):
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "Dagens Meny :fork_and_knife:",
                "emoji": True,
            },
        },
        {"type": "divider"},
    ]

    if "transit" in menu:
        blocks += [
            {"type": "section", "text": {"type": "mrkdwn", "text": "*Transit ⬇️*\n"}},
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"- {item}"}
                    for item in menu["transit"][today]
                ],
            },
            {"type": "divider"},
        ]

    if "expedisjon" in menu:
        blocks += [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*Expedisjon ⬆️*\n"},
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"- {item}"}
                    for item in menu["expedisjon"][today]
                ],
            },
            {"type": "divider"},
        ]

    if openai_parsed:
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "Powered by AI :robot_face:",
                },
            }
        )

    return blocks


def main():
    # Try to get messages for the past week
    start_date = datetime.now()
    # app appears to set this to 23:00 yesterday, not sure why but let's do the same
    end_date = start_date - timedelta(days=1)
    end_date = end_date.replace(hour=23, minute=0, second=0, microsecond=0)

    # Get messages
    messages = parse_melding(start_date, end_date)
    # Extract menu
    menu, openai_parsed = extract_menu(messages["results"])
    logger.debug(f"Menu: {menu}, openai_parsed: {openai_parsed}")
    # Find today's menu
    today = datetime.now().weekday()
    if today > 4:
        print(menu)
        return
    today = DAYS[today]

    # Print menu
    for name in ("transit", "expedisjon"):
        if name not in menu:
            print(f"No menu for {name}")
            continue
        print(f"{name.capitalize()} {today.capitalize()}")
        for item in menu[name][today]:
            print(f" - {item}")
    if openai_parsed:
        print("Powered by OpenAI GPT-3.5 Turbo")

    # Post menu to slack
    blocks = create_slack_message(menu, today, openai_parsed)
    slack_payload = {
        "blocks": blocks,
    }
    if "transit" not in menu and "expedisjon" not in menu:
        print("No menu found, skipping")
        return
    if SLACK_HOOK:
        res = httpx.post(SLACK_HOOK, json=slack_payload)
        res.raise_for_status()
    else:
        print("No slack hook configured, skipping")


if __name__ == "__main__":
    main()
