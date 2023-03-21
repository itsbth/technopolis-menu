import json
import logging
import os
import re
from datetime import datetime, timedelta

import boto3
import httpx
import openai
from dotenv import load_dotenv

load_dotenv()
load_dotenv(".env.local")

# Log to stdout
logging.basicConfig(level=logging.INFO)

logger = logging.getLogger()

SLACK_HOOK = os.environ.get("SLACK_HOOK", None)

PARSE_APPLICATION_ID = os.environ.get("PARSE_APPLICATION_ID")
PARSE_CLIENT_KEY = os.environ.get("PARSE_CLIENT_KEY")
PARSE_INSTALLATION_ID = os.environ.get("PARSE_INSTALLATION_ID")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", None)
OPENAI_ORGANIZATION = os.environ.get("OPENAI_ORGANIZATION", None)

S3_BUCKET = os.environ.get("CACHE_BUCKET", None)
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", None)
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY_ID", None)
S3_SECRET_KEY = os.environ.get("S3_SECRET_ACCESS_KEY", None)

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

DAYS = ("mandag", "tirsdag", "onsdag", "torsdag", "fredag")


def s3_cache(prefix=""):
    """
    Cache the result of the function in S3. Key is the sha256 hash of the first argument.
    In case the function raises an exception, store the exception in S3, and reraise it for the next call.
    This is in order to not spend openai credits on failed requests.
    Format in s3 is JSON, {result: <result>, status} where status is either "success" or "error".
    In case of error, result is the error message, which is reraised as a generic exception.
    """
    import functools

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            import hashlib
            import json

            if (
                not S3_BUCKET
                or not S3_ENDPOINT
                or not S3_ACCESS_KEY
                or not S3_SECRET_KEY
            ):
                raise ValueError("Missing S3 config, bail out")

            digest = hashlib.sha256(str(args[0]).encode("utf-8")).hexdigest()
            if prefix:
                key = f"{prefix}/{digest[:2]}/{digest}"
            else:
                key = f"{digest[:2]}/{digest}"
            s3 = boto3.resource(
                "s3",
                endpoint_url=S3_ENDPOINT,
                aws_access_key_id=S3_ACCESS_KEY,
                aws_secret_access_key=S3_SECRET_KEY,
            )
            try:
                obj = s3.Object(S3_BUCKET, key)
                data = json.loads(obj.get()["Body"].read().decode("utf-8"))
                logger.info(f"Got {key} from cache")
                if data["status"] == "error":
                    logger.warn(f"Got error from cache: {data['result']}")
                    raise Exception(data["result"])
                return data["result"]
            except s3.meta.client.exceptions.NoSuchKey:
                try:
                    result = fn(*args, **kwargs)
                    obj.put(Body=json.dumps({"result": result, "status": "success"}))
                    return result
                except Exception as e:
                    obj.put(Body=json.dumps({"result": str(e), "status": "error"}))
                    raise e

        return wrapper

    return decorator


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
                except Exception as e:
                    import traceback

                    traceback.print_exc()
                    result[cantina] = parse_menu_simple(message["langBeskrivelse"])
    return result, openai_parsed


def parse_menu_simple(menu: str):
    days = {}
    menu = menu.split("\n\n")
    day = None
    for line in menu:
        if line.lower() in DAYS:
            day = line.lower()
            days[day] = []
        elif day and line:
            days[day].append(line.strip())
    return days


@s3_cache(prefix="v1")
def parse_menu_gpt(menu: str):
    """
    Use OpenAI to extract the menu from the text.
    TODO: Handle caching, no need to call OpenAI every time
    """
    if not OPENAI_API_KEY or not OPENAI_ORGANIZATION:
        raise ValueError("Missing OpenAI API key or organization")
    openai.organization = OPENAI_ORGANIZATION
    openai.api_key = OPENAI_API_KEY

    logger.info("Calling OpenAI")

    result = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        temperature=0.0,
        max_tokens=2048,
        messages=[
            {
                "role": "system",
                "content": "You are an assistant designed to parse unstructured text into JSON. You will be given a short description, the expected format, and the unstructured text. You are the reply with only the JSON response.",
            },
            {
                "role": "user",
                "content": "This is the menu from a cantina, but the text is somewhat malformed. Please respond with only a JSON document where each key is a day, and the value is an array of the options for that day. Do not translate the options, but use the keys [mandag, tirsdag, onsdag, torsdag, fredag].",
            },
            {"role": "user", "content": menu},
        ],
    )

    # Log token usage
    # TODO: Re-enable when I know it's working.
    # logger.info(f"OpenAI tokens used: {result.usage.total_tokens}")

    # Hopefully it follows the prompt and returns a JSON document
    return json.loads(result.choices[0].message["content"])


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
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*Transit ⬇️*\n"}},
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
                "text": {"type": "mrkdwn", "text": f"*Expedisjon ⬆️*\n"},
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
                    "emoji": True,
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
