from collections import defaultdict
from datetime import timezone
from email.utils import parsedate_to_datetime

from gmail.analyzer import get_header


def find_duplicates(messages_with_headers):
    """
    Detect duplicate emails using two strategies:
      1. Same Message-ID header (definitive duplicate)
      2. Same sender + subject + date rounded to the minute (fuzzy match)

    Returns a list of groups, where each group is a list of message IDs.
    The first ID in each group is kept; the rest are considered duplicates.
    """
    by_message_id = defaultdict(list)
    no_message_id = []

    for msg_id, headers in messages_with_headers:
        mid = get_header(headers, "Message-ID").strip()
        if mid:
            by_message_id[mid].append(msg_id)
        else:
            no_message_id.append((msg_id, headers))

    groups = [ids for ids in by_message_id.values() if len(ids) > 1]

    # Fuzzy match for emails missing Message-ID
    fuzzy = defaultdict(list)
    for msg_id, headers in no_message_id:
        sender = get_header(headers, "From")
        subject = get_header(headers, "Subject")
        date_str = get_header(headers, "Date")
        try:
            dt = parsedate_to_datetime(date_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            key = (sender, subject, dt.replace(second=0, microsecond=0))
        except Exception:
            key = (sender, subject, "")
        fuzzy[key].append(msg_id)

    groups += [ids for ids in fuzzy.values() if len(ids) > 1]
    return groups
