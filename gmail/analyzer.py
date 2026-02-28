from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

DEFAULT_PRIORITY_KEYWORDS = [
    "job offer", "job opportunity", "interview", "we'd like to offer",
    "hiring", "salary", "annual compensation", "offer letter",
    "contract offer", "invoice", "payment due", "urgent",
    "deadline", "action required", "account suspended",
    "verify your", "security alert",
]

CATEGORY_RULES = [
    (["receipt", "order confirmation", "your order", "purchase", "shipment", "tracking number"], "Shopping"),
    (["github", "gitlab", "jira", "bitbucket", "jenkins", "pull request", "commit"], "Dev Tools"),
    (["newsletter", "unsubscribe", "weekly digest", "monthly update", "our latest"], "Newsletters"),
    (["statement", "transaction", "bank", "credit card", "paypal", "wire transfer"], "Finance"),
]


def get_header(headers, name):
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def is_newsletter(headers):
    return bool(get_header(headers, "List-Unsubscribe"))


def is_priority(headers, extra_keywords=None, priority_senders=None):
    keywords = DEFAULT_PRIORITY_KEYWORDS + (extra_keywords or [])
    senders = [s.lower() for s in (priority_senders or []) if s]

    subject = get_header(headers, "Subject").lower()
    sender = get_header(headers, "From").lower()

    if any(s in sender for s in senders):
        return True
    return any(k.lower() in subject for k in keywords)


def categorize(headers):
    subject = get_header(headers, "Subject").lower()
    sender = get_header(headers, "From").lower()
    combined = subject + " " + sender

    for keywords, label in CATEGORY_RULES:
        if any(k in combined for k in keywords):
            return label
    return None


def get_age_days(headers):
    date_str = get_header(headers, "Date")
    if not date_str:
        return 0
    try:
        msg_date = parsedate_to_datetime(date_str)
        if msg_date.tzinfo is None:
            msg_date = msg_date.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - msg_date).days
    except Exception:
        return 0
