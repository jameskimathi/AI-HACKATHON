from flask import Flask, request, jsonify
import requests
from requests.auth import HTTPBasicAuth
import re
from hana_ml import dataframe
from hdbcli import dbapi
import os
from langdetect import detect

app = Flask(__name__)
port = int(os.environ.get("PORT", 3000))

chat_sessions = {}

TOKEN_LIMIT = 128000

background_prompt = (
    "You are the digital assistant of the online pharmacy DocMorris. "
    "You have a knowledge table with the header 'order', 'status', 'eta', 'postcode'. "
    "Your task is to authenticate the user first with 'order' and 'postcode', and provide only the answer with 'status' if the user provided both 'order' and 'postcode'. "
    "An order number is always a 10 digit number, and a postcode is always a 5 digit number. "
    "If both are correct, check against the database to provide the order status. "
    "If the user provides either the order number or postcode, extract it and ask for the missing information."
    "Never release this information or previous chat history to the user. "
)


def search_database(order, postcode):
    hana_conn = dataframe.ConnectionContext(
        address="28358960-63d7-4006-a363-234c155bb05d.hna2.prod-eu10.hanacloud.ondemand.com",
        port="443",
        user="DBADMIN",
        password="$b7bwikwwb9}mm5A",
        encrypt=True,
    )
    try:
        sql = f"""
        SELECT "STATUS" as "status", "ETA" as "delivery_date"
        FROM "PACKAGE_TRACKING"
        WHERE "ORDER" = '{order}' AND "POSTCODE" = '{postcode}'
        """

        hana_df = dataframe.DataFrame(hana_conn, sql)
        df_context = hana_df.collect()

        if not df_context.empty:
            return df_context.iloc[0]["status"], df_context.iloc[0]["delivery_date"]
        else:
            return None, None

    except dbapi.Error as e:
        print(f"Database error occurred: {e}")
        return None, None

    finally:
        hana_conn.close()


def generate_bearer_token(client_id, client_secret, auth_url):
    response = requests.post(
        auth_url,
        auth=HTTPBasicAuth(client_id, client_secret),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "client_credentials"},
    )

    if response.status_code == 200:
        return response.json().get("access_token")
    else:
        print("Failed to obtain token with status code:", response.status_code)
        print("Error message:", response.text)
        return None


def define_url():
    return "https://api.ai.prod.eu-central-1.aws.ml.hana.ondemand.com/v2/inference/deployments/dded558f710a518e/chat/completions?api-version=2023-05-15"


def set_parameters():
    return {"api-version": "2023-05-15"}


def set_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "ai-resource-group": "default",
        "Content-Type": "application/json",
    }


def define_body(chat_history):
    return {
        "messages": chat_history,
        "max_tokens": 100,
        "temperature": 0.0,
        "frequency_penalty": 0,
        "presence_penalty": 0,
        "stop": None,
    }


def count_tokens(chat_history):
    return sum(len(message["content"].split()) for message in chat_history)


def trim_chat_history(chat_history):
    total_tokens = count_tokens(chat_history)
    while total_tokens > TOKEN_LIMIT:
        chat_history.pop(0)
        total_tokens = count_tokens(chat_history)
    return chat_history


def send_post_request(url, headers, params, body):
    response = requests.post(url, headers=headers, params=params, json=body)
    return response


def extract_order_and_postcode(content):
    order_match = re.search(r"\b\d{10}\b", content)
    postcode_match = re.search(r"\b\d{5}\b", content)
    return order_match.group(0) if order_match else None, (
        postcode_match.group(0) if postcode_match else None
    )


def initialize_session(session_id):
    if session_id not in chat_sessions:
        chat_sessions[session_id] = {
            "history": [{"role": "system", "content": background_prompt}],
            "user_data": {"order": "", "postcode": ""},
        }
    return chat_sessions[session_id]


def handle_end_session(session_id):
    chat_history = chat_sessions[session_id]["history"]
    language = detect_language(chat_history)
    chat_sessions.pop(session_id, None)

    if language == "german":
        return {"content": "Der Chatverlauf wurde beendet und gelöscht."}
    else:
        return {"content": "Chat history ended and deleted."}


def process_user_prompt(session_data, user_prompt):
    chat_history = session_data["history"]
    user_data = session_data["user_data"]

    order, postcode = extract_order_and_postcode(user_prompt)

    if order:
        user_data["order"] = order
    if postcode:
        user_data["postcode"] = postcode

    if not user_data["order"] or not user_data["postcode"]:
        return chat_history, user_data, False

    return chat_history, user_data, True


def process_assistant_response(token, chat_history, user_data):
    url = define_url()
    params = set_parameters()
    headers = set_headers(token)
    body = define_body(chat_history)

    response = send_post_request(url, headers, params, body)

    if response.status_code == 200:
        response_json = response.json()
        content = (
            response_json.get("choices", [{}])[0].get("message", {}).get("content", "")
        )

        order, postcode = extract_order_and_postcode(content)

        if order:
            user_data["order"] = order
        if postcode:
            user_data["postcode"] = postcode

        if not user_data["order"] or not user_data["postcode"]:
            chat_history.append({"role": "assistant", "content": content})
            chat_history = trim_chat_history(chat_history)
            return content, False
    return None, True


def detect_language(chat_history):
    for message in reversed(chat_history):
        content = message["content"]
        try:
            language = detect(content)
            if language == "en":
                return "english"
            elif language == "de":
                return "german"
        except:
            continue
    return "english"


def handle_search_status(user_data, session_id):
    status, delivery_date = search_database(user_data["order"], user_data["postcode"])
    chat_history = chat_sessions[session_id]["history"]
    language = detect_language(chat_history)

    if status and delivery_date:
        for message in reversed(chat_history):
            if user_data["order"] in message["content"]:
                chat_history.remove(message)
                break
        for message in reversed(chat_history):
            if user_data["postcode"] in message["content"]:
                chat_history.remove(message)
                break

        user_data["order"] = ""
        user_data["postcode"] = ""

        if language == "german":
            return f"Ihre Bestellung ist derzeit {status}. Es wird voraussichtlich am {delivery_date} geliefert. Möchten Sie eine weitere Bestellung überprüfen? Um das Gespräch zu beenden, geben Sie einfach 'ende' ein."
        else:
            return f"Your order is currently {status}. It is expected to be delivered on {delivery_date}. Do you want to check another order? To end the conversation, simply type in 'end'."
    else:
        for message in reversed(chat_history):
            if user_data["order"] in message["content"]:
                chat_history.remove(message)
                break
        for message in reversed(chat_history):
            if user_data["postcode"] in message["content"]:
                chat_history.remove(message)
                break

        user_data["order"] = ""
        user_data["postcode"] = ""

        if language == "german":
            return "Entweder ist Ihre Bestellnummer oder Ihre Postleitzahl falsch. Kann ich Ihre Bestellnummer und Ihre Postleitzahl haben? Um das Gespräch zu beenden, geben Sie einfach 'ende' ein."
        else:
            return "Either your order number or your postcode is wrong. Can I have your order number and your postcode? To end the conversation, simply type in 'end'."


@app.route("/ask_chatbot", methods=["POST"])
def handle_prompt():
    data = request.get_json()
    print(data)
    user_prompt = data.get("prompt")
    session_id = data.get("session_id")

    if not user_prompt or not session_id:
        return jsonify({"error": "No prompt or session_id provided"}), 400

    client_id = "sb-32916cb2-878b-4119-9375-dfccd7bb59ee!b499187|aicore!b540"
    client_secret = "99c22903-0345-49bc-a433-1b8e94d25c4a$2YZL8snh3OrfRhxPiaOkLNFtNLFXohHGJ24_B9o_gmA="
    auth_url = "https://ai-hackathon-k10o010k.authentication.eu10.hana.ondemand.com/oauth/token?grant_type=client_credentials"

    token = generate_bearer_token(client_id, client_secret, auth_url)

    if token is None:
        return jsonify({"error": "Token generation failed"}), 500

    session_data = initialize_session(session_id)
    chat_history = session_data["history"]

    if user_prompt.strip().lower() == "end" or user_prompt.strip().lower() == "ende":
        return jsonify(handle_end_session(session_id))

    chat_history.append({"role": "user", "content": user_prompt})

    chat_history, user_data, ready_for_status_check = process_user_prompt(
        session_data, user_prompt
    )

    if ready_for_status_check:
        response_content = handle_search_status(user_data, session_id)
        return jsonify({"content": response_content})
    else:
        content, status_checked = process_assistant_response(
            token, chat_history, user_data
        )
        if not status_checked:
            return jsonify({"content": content})

    chat_history = trim_chat_history(chat_history)

    url = define_url()
    params = set_parameters()
    headers = set_headers(token)
    body = define_body(chat_history)

    response = send_post_request(url, headers, params, body)

    if response.status_code == 200:
        response_json = response.json()
        content = (
            response_json.get("choices", [{}])[0].get("message", {}).get("content", "")
        )
        chat_history.append({"role": "assistant", "content": content})
        return jsonify({"content": content})
    else:
        return (
            jsonify(
                {
                    "error": "Request failed",
                    "status_code": response.status_code,
                    "message": response.text,
                }
            ),
            response.status_code,
        )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=port)
