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
    ([
        "% off", "off today", "sale ends", "flash sale", "clearance", "shop now",
        "limited time", "exclusive offer", "special offer", "today only", "deal of",
        "free shipping", "new arrivals", "back in stock", "just for you", "don't miss",
        "save up to", "extra savings", "coupon", "promo code", "discount code",
        "you might like", "we picked these", "check out our", "shop the",
    ], "Store Promos"),
    (["github", "gitlab", "jira", "bitbucket", "jenkins", "pull request", "commit"], "Dev Tools"),
    (["newsletter", "unsubscribe", "weekly digest", "monthly update", "our latest"], "Newsletters"),
    ([
        "charged", "you've been charged", "charge of",
        "subscription", "your subscription", "subscription renewal", "subscription confirmed",
        "billing", "your bill",
        "auto-renew", "autorenewal", "auto renewal", "renewal notice",
        "payment received", "payment confirmed", "payment processed", "payment successful",
        "monthly charge", "annual charge", "recurring charge",
        "your plan", "plan renewal",
    ], "Billing & Payments"),
    (["statement", "transaction", "bank", "credit card", "paypal", "wire transfer"], "Finance"),
]


def get_header(headers, name):
    for h in headers:
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


_JOB_EMAIL_KEYWORDS = [
    # Recruiter outreach
    "recruiter", "recruiting", "talent acquisition", "i came across your profile",
    "your background", "your experience", "reach out",
    # Opportunities
    "job offer", "job opportunity", "new opportunity", "exciting opportunity",
    "open position", "open role", "we are hiring", "we're hiring", "join our team",
    "we'd like to offer", "offer letter",
    # Interviews & process
    "interview", "phone screen", "technical screen", "coding challenge",
    "take-home", "onsite", "virtual interview", "next steps",
    "your application", "application received", "application status",
    "applied for", "thank you for applying",
    # Compensation
    "salary", "compensation", "equity", "stock options", "benefits package",
    # Job alerts from platforms
    "job alert", "jobs matching", "jobs for you", "new jobs",
    "career opportunity", "career alert",
]

_JOB_EMAIL_SENDERS = [
    "linkedin", "indeed", "glassdoor", "ziprecruiter", "monster",
    "talent.com", "workopolis", "simplyhired", "careerbuilder",
    "lever.co", "greenhouse.io", "workday", "ashby", "rippling",
    "jobvite", "smartrecruiters", "icims", "taleo", "wellfound",
]


def is_job_email(headers) -> bool:
    """Return True if the email looks job/career related."""
    subject = get_header(headers, "Subject").lower()
    sender = get_header(headers, "From").lower()
    combined = subject + " " + sender
    return (
        any(k in combined for k in _JOB_EMAIL_KEYWORDS)
        or any(s in combined for s in _JOB_EMAIL_SENDERS)
    )


def is_newsletter(headers):
    return bool(get_header(headers, "List-Unsubscribe"))


_AUTOMATED_SENDER_PATTERNS = [
    "no-reply", "noreply", "do-not-reply", "donotreply",
    "notifications@", "notify@", "automated@", "mailer@",
    "bounce@", "postmaster@", "alert@", "alerts@",
    "news@", "newsletter@", "marketing@", "promo@",
    "support@", "hello@", "info@", "team@", "accounts@",
    "update@", "updates@", "service@", "system@",
]


def is_personal_email(headers) -> bool:
    """Return True if the email looks like it was sent directly by a real person."""
    # Any bulk/list header means it's not personal
    if get_header(headers, "List-Unsubscribe"):
        return False
    if get_header(headers, "List-Id"):
        return False

    # Precedence: bulk / list / junk → automated
    precedence = get_header(headers, "Precedence").lower()
    if precedence in ("bulk", "list", "junk"):
        return False

    # Sender looks automated
    sender = get_header(headers, "From").lower()
    if any(p in sender for p in _AUTOMATED_SENDER_PATTERNS):
        return False

    return True


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
