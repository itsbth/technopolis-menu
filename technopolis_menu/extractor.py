import json
import logging
import os

import boto3
import openai

logger = logging.getLogger(__name__)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", None)
OPENAI_ORGANIZATION = os.environ.get("OPENAI_ORGANIZATION", None)
S3_BUCKET = os.environ.get("CACHE_BUCKET", None)
S3_ENDPOINT = os.environ.get("S3_ENDPOINT", None)
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY_ID", None)
S3_SECRET_KEY = os.environ.get("S3_SECRET_ACCESS_KEY", None)
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


# For robustness, try a short (and cheap) prompt first, and then a longer one if that fails.
GPT_PROMPTS = [
    [
        {
            "role": "system",
            "content": "Send me a Norwegian cantina menu, and I'll return a JSON document with arrays of dishes for each day of the week, using the keys [mandag, tirsdag, onsdag, torsdag, fredag].",
        }
    ],
    [
        {
            "role": "system",
            "content": "You are an assistant designed to parse unstructured text into JSON. You will be given a short description, the expected format, and the unstructured text. You are the reply with only the JSON response.",
        },
        {
            "role": "user",
            "content": "This is the menu from a cantina, but the text is somewhat malformed. Please respond with only a JSON document where each key is a day, and the value is an array of the options for that day. Do not translate the options, but use the keys [mandag, tirsdag, onsdag, torsdag, fredag].",
        },
    ],
]


def verify_menu_structure(menu_json):
    days_of_week = ["mandag", "tirsdag", "onsdag", "torsdag", "fredag"]

    for day in days_of_week:
        if day not in menu_json:
            return False
        if not isinstance(menu_json[day], list):
            return False
        for dish in menu_json[day]:
            if not isinstance(dish, str):
                return False
    return True


@s3_cache(prefix="v1")
def parse_menu_gpt(menu: str):
    """
    Use OpenAI to extract the menu from the text.
    """
    if not OPENAI_API_KEY or not OPENAI_ORGANIZATION:
        raise ValueError("Missing OpenAI API key or organization")
    openai.organization = OPENAI_ORGANIZATION
    openai.api_key = OPENAI_API_KEY

    logger.info("Calling OpenAI")
    for prompt in GPT_PROMPTS:
        result = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            temperature=0.0,
            max_tokens=2048,
            messages=prompt + [{"role": "user", "content": menu}],
        )
        try:
            menu_json = json.loads(result.choices[0].text)
            if verify_menu_structure(menu_json):
                return menu_json
        except json.JSONDecodeError:
            pass

    raise Exception("Could not parse menu")