from flask import Flask, request, jsonify
import requests
from requests.auth import HTTPBasicAuth
import csv
import re

app = Flask(__name__)

# In-memory storage for chat sessions
chat_sessions = {}

TOKEN_LIMIT = 128000

background_prompt = (
    "You are the digital assistant of the online pharmacy DocMorris. "
    "You have a knowledge table with the header 'order', 'status', 'eta', 'postcode'. "
    "Your task is to authenticate the user first with 'order' and 'postcode', and provide only the answer with 'status' if the user provided both 'order' and 'postcode'. "
    "An order number is always a 10 digit number, and a postcode is always a 5 digit number. "
    "If both are correct, check against the database to provide the order status. "
    "If the user provides either the order number or postcode, extract it and ask for the missing information."
)


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


def search_database(order, postcode):
    with open("database.csv", mode="r") as file:
        reader = csv.DictReader(file, delimiter=";")
        for row in reader:
            if row["ORDER"] == order and row["POSTCODE"] == postcode:
                return row["STATUS"]
    return None


@app.route("/api/prompt", methods=["POST"])
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

    # Retrieve or initialize chat history for the session
    if session_id not in chat_sessions:
        chat_sessions[session_id] = {
            "history": [{"role": "system", "content": background_prompt}],
            "user_data": {"order": "", "postcode": ""},
        }

    session_data = chat_sessions[session_id]
    chat_history = session_data["history"]
    user_data = session_data["user_data"]

    chat_history.append({"role": "user", "content": user_prompt})

    if user_prompt.strip().lower() == "end":
        chat_sessions.pop(session_id, None)
        return jsonify({"message": "Chat history ended and deleted."})

    if not user_data["order"] or not user_data["postcode"]:
        url = define_url()
        params = set_parameters()
        headers = set_headers(token)
        body = define_body(chat_history)

        response = send_post_request(url, headers, params, body)

        if response.status_code == 200:
            response_json = response.json()
            content = (
                response_json.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )

            order_match = re.search(r"\b\d{10}\b", content)
            postcode_match = re.search(r"\b\d{5}\b", content)

            if order_match:
                user_data["order"] = order_match.group(0)
            if postcode_match:
                user_data["postcode"] = postcode_match.group(0)

            if not user_data["order"] or not user_data["postcode"]:
                chat_history.append({"role": "assistant", "content": content})
                # Check token limit and trim chat history if necessary
                chat_history = trim_chat_history(chat_history)
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

    status = search_database(user_data["order"], user_data["postcode"])
    if status:
        chat_history.append(
            {"role": "assistant", "content": f"Your order is currently {status}."}
        )
        user_data["order"] = ""
        user_data["postcode"] = ""
    else:
        chat_history.append(
            {
                "role": "assistant",
                "content": "Either your order number or your postcode is wrong. Can I have your order number and your postcode?",
            }
        )
        user_data["order"] = ""
        user_data["postcode"] = ""

    # Check token limit and trim chat history if necessary
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

        # Add assistant's response to chat history
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
    app.run(debug=True)


# client_id = "sb-32916cb2-878b-4119-9375-dfccd7bb59ee!b499187|aicore!b540"
# client_secret = "99c22903-0345-49bc-a433-1b8e94d25c4a$2YZL8snh3OrfRhxPiaOkLNFtNLFXohHGJ24_B9o_gmA="
# auth_url = "https://ai-hackathon-k10o010k.authentication.eu10.hana.ondemand.com/oauth/token?grant_type=client_credentials"
