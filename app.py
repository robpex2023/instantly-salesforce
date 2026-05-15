"""
Instantly -> Salesforce Live Webhook
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

def get_sf():
    return Salesforce(
        username=os.getenv("SF_USERNAME"),
        password=os.getenv("SF_PASSWORD"),
        security_token=os.getenv("SF_SECURITY_TOKEN"),
        domain=os.getenv("SF_DOMAIN", "login"),
    )

def classify_intent(subject, body):
    text = (str(subject) + " " + str(body)).lower()
    if re.search(r"\b(interested|tell me more|sounds good|yes|let'?s chat|book|schedule|call me|demo)\b", text):
        return "Interested"
    if re.search(r"\b(not interested|unsubscribe|remove me|no thanks|opt.?out|stop emailing)\b", text):
        return "Not Interested"
    if re.search(r"\b(out of office|ooo|on vacation|annual leave|away until|back on|returning)\b", text):
        return "Out of Office"
    if re.search(r"\b(refer|referred|talk to|reach out to|contact my|colleague|passed you on)\b", text):
        return "Referral"
    if re.search(r"\b(question|wondering|clarif|more info|can you|could you|how does)\b", text):
        return "Question"
    return "General Reply"

TASK_CONFIG = {
    "Interested":     {"subject": "Interested reply -- book a call",       "priority": "High",   "days": 1},
    "Not Interested": {"subject": "Mark lead as closed -- not interested", "priority": "Normal", "days": 3},
    "Out of Office":  {"subject": "Follow up when back from OOO",          "priority": "Normal", "days": 7},
    "Referral":       {"subject": "Referral received -- create new lead",  "priority": "High",   "days": 1},
    "Question":       {"subject": "Reply with question -- respond today",  "priority": "High",   "days": 1},
    "General Reply":  {"subject": "New reply -- review and respond",       "priority": "Normal", "days": 2},
}

def find_lead(sf, email):
    try:
        email = email.replace("'", "\\'")
        query = f"""
            SELECT Id, Name FROM Lead
            WHERE IsConverted = false
            AND (
                Email = '{email}' OR
                Email_2__c = '{email}' OR
                Updated_Email__c = '{email}' OR
                Updated_Email_2__c = '{email}' OR
                Updated_Email_3__c = '{email}'
            )
            LIMIT 1
        """
        result = sf.query(query)
        records = result.get("records", [])
        return records[0] if records else None
    except Exception as e:
        print(f"  Error finding lead for {email}: {e}")
        return None

def log_activity(sf, lead_id, subject, body, reply_date):
    sf.Task.create({
        "WhoId":        lead_id,
        "Subject":      f"INSTANTLY REPLY: {subject}",
        "Description":  body,
        "ActivityDate": reply_date.strftime("%Y-%m-%d"),
        "Status":       "Completed",
        "Priority":     "Normal",
    })

def create_task(sf, lead_id, intent):
    config = TASK_CONFIG.get(intent, TASK_CONFIG["General Reply"])
    due_date = date.today() + timedelta(days=config["days"])
    sf.Task.create({
        "WhoId":        lead_id,
        "Subject":      config["subject"],
        "Priority":     config["priority"],
        "Status":       "Not Started",
        "ActivityDate": due_date.strftime("%Y-%m-%d"),
        "Description":  f"Auto-created from Instantly reply. Intent: {intent}",
        "OwnerId":      os.getenv("SF_OWNER_ID"),
    })

@app.route("/webhook/instantly-reply", methods=["POST"])
def instantly_reply():
    payload = request.json or {}

    from_email = payload.get("from_address") or payload.get("reply_from_email") or payload.get("from_address_email", "")
    subject    = payload.get("subject")    or payload.get("email_subject", "") or ""
    body_raw   = payload.get("body_text")  or payload.get("reply_body")        or payload.get("body", "")
    body       = body_raw.get("text", "") if isinstance(body_raw, dict) else (body_raw or "")
    reply_date = datetime.utcnow()

    if not from_email:
        print("No sender email in payload")
        return jsonify({"received": True})

    intent = classify_intent(subject, body)
    print(f"[{from_email}] Intent: {intent}")

    try:
        sf = get_sf()
        lead = find_lead(sf, from_email)

        if not lead:
            print(f"No Lead found for {from_email}")
            return jsonify({"received": True})

        log_activity(sf, lead["Id"], subject, body, reply_date)
        create_task(sf, lead["Id"], intent)
        print(f"Done -- {intent} for {from_email}")

    except Exception as e:
        print(f"Error: {e}")
        print(traceback.format_exc())

    return jsonify({"received": True})

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
