from googleapiclient.discovery import build


def build_service(creds):
    return build("gmail", "v1", credentials=creds)


def list_messages(service, query="", max_results=500):
    """Return a list of message dicts (id, threadId) matching the query."""
    messages = []
    request = service.users().messages().list(
        userId="me", q=query, maxResults=min(max_results, 500)
    )
    while request is not None and len(messages) < max_results:
        response = request.execute()
        messages.extend(response.get("messages", []))
        request = service.users().messages().list_next(request, response)
    return messages[:max_results]


def get_message_metadata(service, msg_id):
    """Fetch a message with only the headers we care about (fast, low quota)."""
    return service.users().messages().get(
        userId="me",
        id=msg_id,
        format="metadata",
        metadataHeaders=["Subject", "From", "Date", "List-Unsubscribe", "Message-ID"],
    ).execute()


def trash_message(service, msg_id):
    service.users().messages().trash(userId="me", id=msg_id).execute()


def modify_labels(service, msg_id, add_labels=None, remove_labels=None):
    body = {}
    if add_labels:
        body["addLabelIds"] = add_labels
    if remove_labels:
        body["removeLabelIds"] = remove_labels
    service.users().messages().modify(userId="me", id=msg_id, body=body).execute()


def get_or_create_label(service, name):
    """Return the label ID for `name`, creating the label if it doesn't exist."""
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    for label in labels:
        if label["name"].lower() == name.lower():
            return label["id"]
    result = service.users().labels().create(userId="me", body={"name": name}).execute()
    return result["id"]
