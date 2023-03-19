import os
import re
from datetime import datetime, timedelta

import httpx
from dotenv import load_dotenv

load_dotenv()
load_dotenv(".env.local")

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


def parse_melding(start_date, end_date):
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
    return response.json()


MENU_TEXT_REGEX = re.compile(
    r"Meny uke (?P<week>\d+), (?P<cantina>Expedisjon|Transit) \d\.etg"
)

DAYS = ("mandag", "tirsdag", "onsdag", "torsdag", "fredag")


def extract_menu(messages):
    result = {}
    for message in messages:
        if m := MENU_TEXT_REGEX.match(message["tekst"]):
            cantina = m.group("cantina").lower()
            if cantina not in result:
                result[cantina] = {}
            if "langBeskrivelse" in message:
                menu = message["langBeskrivelse"].split("\n\n")
                day = None
                for line in menu:
                    if line.lower() in DAYS:
                        day = line.lower()
                        result[cantina][day] = []
                    elif day and line:
                        result[cantina][day].append(line.strip())
    return result


def create_slack_message(menu, today):
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
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Transit ⬇️*\n"}},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"- {item}"}
                for item in menu["transit"][today]
            ],
        },
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Expedisjon ⬆️*\n"}},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"- {item}"}
                for item in menu["expedisjon"][today]
            ],
        },
    ]

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
    menu = extract_menu(messages["results"])
    # Find today's menu
    today = datetime.now().weekday()
    if today > 4:
        print(menu)
        return
    today = DAYS[today]

    # Print menu
    for name in ("transit", "expedisjon"):
        print(f"{name.capitalize()} {today.capitalize()}")
        for item in menu[name][today]:
            print(f" - {item}")

    # Post menu to slack
    blocks = create_slack_message(menu, today)
    slack_payload = {
        "blocks": blocks,
    }
    if SLACK_HOOK:
        res = httpx.post(SLACK_HOOK, json=slack_payload)
        res.raise_for_status()
    else:
        print("No slack hook configured, skipping")


if __name__ == "__main__":
    main()
