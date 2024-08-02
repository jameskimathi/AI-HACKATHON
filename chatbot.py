from flask import Flask, request, jsonify
import requests
from requests.auth import HTTPBasicAuth
import re
from hana_ml import dataframe
from hdbcli import dbapi

app = Flask(__name__)

chat_sessions = {}

background_prompt = (
    "You are the digital assistant of the online pharmacy DocMorris. "
    "You have a knowledge table with the header 'order', 'status', 'eta', 'postcode'. "
    "Your task is to authenticate the user first with 'order' and 'postcode', and provide only the answer with 'status' if the user provided both 'order' and 'postcode'. "
    "An order number is always a 10 digit number, and a postcode is always a 5 digit number. "
    "If both are correct, check against the database to provide the order status. "
    "If the user provides either the order number or postcode, extract it and ask for the missing information."
)

hana_conn = dataframe.ConnectionContext(
    address="28358960-63d7-4006-a363-234c155bb05d.hna2.prod-eu10.hanacloud.ondemand.com",
    port="443",
    user="DBADMIN",
    password="$b7bwikwwb9}mm5A",
    encrypt=True,
)


def search_database(order, postcode):
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


def define_body(prompt):
    return {
        "messages": [
            {"role": "system", "content": background_prompt},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 100,
        "temperature": 0.0,
        "frequency_penalty": 0,
        "presence_penalty": 0,
        "stop": None,
    }


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
        chat_sessions[session_id] = {"user_data": {"order": "", "postcode": ""}}
    return chat_sessions[session_id]


def handle_end_session(session_id):
    chat_sessions.pop(session_id, None)
    return {"message": "Chat history ended and deleted."}


def process_user_prompt(session_data, user_prompt):
    user_data = session_data["user_data"]

    order, postcode = extract_order_and_postcode(user_prompt)

    if order:
        user_data["order"] = order
    if postcode:
        user_data["postcode"] = postcode

    if not user_data["order"] or not user_data["postcode"]:
        return user_data, False

    return user_data, True


def process_assistant_response(token, prompt, user_data):
    url = define_url()
    params = set_parameters()
    headers = set_headers(token)
    body = define_body(prompt)

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
            return content, False
    return content, True


def handle_search_status(user_data):
    status, delivery_date = search_database(user_data["order"], user_data["postcode"])
    if status:
        user_data["order"] = ""
        user_data["postcode"] = ""
        return f"Your order is currently {status}. It is expected to be delivered on {delivery_date}. Do you want to check another order? To end the conversation, simply type in 'end'."
    else:
        user_data["order"] = ""
        user_data["postcode"] = ""
        return "Either your order number or your postcode is wrong. Can I have your order number and your postcode? To end the conversation, simply type in 'end'."


@app.route("/ask_chatbot", methods=["POST"])
def handle_prompt():
    data = request.get_json()
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

    if user_prompt.strip().lower() == "end":
        return jsonify(handle_end_session(session_id))

    user_data, ready_for_status_check = process_user_prompt(session_data, user_prompt)

    if ready_for_status_check:
        response_content = handle_search_status(user_data)
        return jsonify({"content": response_content})
    else:
        content, status_checked = process_assistant_response(
            token, user_prompt, user_data
        )
        if not status_checked:
            return jsonify({"content": content})

    content, _ = process_assistant_response(token, user_prompt, user_data)
    return jsonify({"content": content})


if __name__ == "__main__":
    app.run(debug=True)
