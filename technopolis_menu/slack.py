import logging
import os
from datetime import datetime

import httpx

from .stats import incr_stat

logger = logging.getLogger(__name__)

SLACK_HOOK = os.environ.get("SLACK_HOOK", None)


# Friendly names, including emoji indicating direction
CANTINA_NAMES = {
    "expedisjon": "Expedisjon ⬆️",
    "transit": "Transit ⬇️",
}


def create_slack_message(menu: dict, today: datetime):
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

    openai_parsed = False

    for cantina in ["expedisjon", "transit"]:
        if cantina not in menu:
            continue
        items = menu[cantina]["simple"]
        if "gpt" in menu[cantina]:
            items = menu[cantina]["gpt"]
            openai_parsed = True
        blocks += [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*{CANTINA_NAMES[cantina]}*\n"},
            },
            {
                "type": "section",
                "fields": [{"type": "mrkdwn", "text": f"- {item}"} for item in items[today]],
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


def post_to_slack(slack_payload):
    res = httpx.post(SLACK_HOOK, json=slack_payload)
    res.raise_for_status()


def run_slack_post(today, menu):
    # Post menu to slack
    blocks = create_slack_message(menu, today)
    slack_payload = {
        "blocks": blocks,
    }
    if SLACK_HOOK:
        post_to_slack(slack_payload)
        incr_stat("slack_post")
    else:
        logger.warning("No slack hook configured, skipping")
