"""
Instantly -> Salesforce Live Webhook
Logs replies as EmailMessages and creates follow-up Tasks
"""

from flask import Flask, request, jsonify
from simple_salesforce import Salesforce
from dotenv import load_dotenv
from datetime import datetime, timedelta, date
import os
import re
import traceback

load_dotenv()

app = Flask(__name__)


# -----------------------------
# Salesforce Connection
# -----------------------------

def get_sf():
    return Salesforce(
        username=os.getenv("SF_USERNAME"),
        password=os.getenv("SF_PASSWORD"),
        security_token=os.getenv("SF_SECURITY_TOKEN"),
        domain=os.getenv("SF_DOMAIN", "login"),
    )


# -----------------------------
# Classify Reply
# -----------------------------

def classify_intent(subject, body):

    text = f"{subject} {body}".lower()

    if re.search(r"\b(interested|tell me more|sounds good|yes|schedule|book|call)\b", text):
        return "Interested"

    if re.search(r"\b(not interested|unsubscribe|remove me|stop emailing)\b", text):
        return "Not Interested"

    if re.search(r"\b(out of office|ooo|vacation|away)\b", text):
        return "Out of Office"

    if re.search(r"\b(question|can you|could you|more info)\b", text):
        return "Question"

    return "General Reply"


TASK_CONFIG = {
    "Interested": {
        "subject": "Interested reply - book a call",
        "priority": "High",
        "days": 1
    },
    "Not Interested": {
        "subject": "Not interested - review lead",
        "priority": "Normal",
        "days": 3
    },
    "Out of Office": {
        "subject": "Follow up after OOO",
        "priority": "Normal",
        "days": 7
    },
    "Question": {
        "subject": "Reply with requested information",
        "priority": "High",
        "days": 1
    },
    "General Reply": {
        "subject": "Review new Instantly reply",
        "priority": "Normal",
        "days": 2
    }
}


# -----------------------------
# Find Salesforce Lead
# -----------------------------

def find_lead(sf, email):

    print(f"Searching Salesforce for: {email}", flush=True)

    query = f"""
    SELECT Id, Name
    FROM Lead
    WHERE IsConverted = false
    AND Email = '{email}'
    LIMIT 1
    """

    result = sf.query(query)

    records = result.get("records", [])

    if records:
        print(f"Found Lead: {records[0]['Name']}", flush=True)
        return records[0]

    print("No Salesforce Lead Found", flush=True)

    return None


# -----------------------------
# Log Email Reply
# -----------------------------

def create_email(sf, lead_id, sender, subject, body):

    try:

        sf.EmailMessage.create({

            "ParentId": lead_id,
            "Incoming": True,
            "FromAddress": sender,
            "Subject": subject,
            "TextBody": body,
            "Status": "0"

        })

        print("EmailMessage created", flush=True)

    except Exception:

        print("EmailMessage failed", flush=True)
        traceback.print_exc()


# -----------------------------
# Create Task
# -----------------------------

def create_task(sf, lead_id, intent):

    config = TASK_CONFIG[intent]

    due = date.today() + timedelta(days=config["days"])

    sf.Task.create({

        "WhoId": lead_id,
        "Subject": config["subject"],
        "Priority": config["priority"],
        "Status": "Not Started",
        "ActivityDate": due.strftime("%Y-%m-%d"),
        "OwnerId": os.getenv("SF_OWNER_ID"),
        "Description": f"Created automatically from Instantly reply. Intent: {intent}"

    })

    print("Task created", flush=True)


# -----------------------------
# Instantly Webhook
# -----------------------------

@app.route("/webhook/instantly-reply", methods=["POST"])
def instantly_reply():

    payload = request.get_json(force=True, silent=True) or {}

    print("====================", flush=True)
    print("INSTANTLY REPLY RECEIVED", flush=True)
    print(payload, flush=True)
    print("====================", flush=True)


    sender = (
        payload.get("from_address")
        or payload.get("from_email")
        or payload.get("reply_from_email")
        or payload.get("email")
        or ""
    )


    subject = (
        payload.get("subject")
        or payload.get("email_subject")
        or ""
    )


    body = (
        payload.get("body_text")
        or payload.get("reply_body")
        or payload.get("text")
        or payload.get("body")
        or ""
    )


    if isinstance(body, dict):
        body = body.get("text", "")


    if not sender:

        print("NO EMAIL FOUND IN PAYLOAD", flush=True)

        return jsonify({"received": True})


    intent = classify_intent(subject, body)

    print(
        f"{sender} classified as {intent}",
        flush=True
    )


    try:

        sf = get_sf()

        lead = find_lead(sf, sender)

        if not lead:

            return jsonify({"received": True})


        create_email(
            sf,
            lead["Id"],
            sender,
            subject,
            body
        )


        create_task(
            sf,
            lead["Id"],
            intent
        )


        print("COMPLETE", flush=True)


    except Exception:

        print("MAIN ERROR", flush=True)
        traceback.print_exc()


    return jsonify({
        "received": True
    })


# -----------------------------
# Health Check
# -----------------------------

@app.route("/health")
def health():

    return jsonify({
        "status": "ok"
    })


if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000
    )
