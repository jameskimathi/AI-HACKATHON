import requests
import json
from requests.auth import HTTPBasicAuth


def generate_bearer_token(client_id, client_secret, auth_url):
    # Function to generate the bearer token using client ID and client secret
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


def define_body():
    return {
        "messages": [{"role": "user", "content": "Tell me about singularity"}],
        "max_tokens": 100,
        "temperature": 0.0,
        "frequency_penalty": 0,
        "presence_penalty": 0,
        "stop": None,
    }


def send_post_request(url, headers, params, body):
    response = requests.post(url, headers=headers, params=params, json=body)
    return response


def main():
    client_id = "sb-32916cb2-878b-4119-9375-dfccd7bb59ee!b499187|aicore!b540"
    client_secret = "99c22903-0345-49bc-a433-1b8e94d25c4a$2YZL8snh3OrfRhxPiaOkLNFtNLFXohHGJ24_B9o_gmA="
    auth_url = "https://ai-hackathon-k10o010k.authentication.eu10.hana.ondemand.com/oauth/token?grant_type=client_credentials"  # Replace with your actual auth URL

    token = generate_bearer_token(client_id, client_secret, auth_url)

    if token is None:
        print("Token generation failed.")
        return

    url = define_url()
    params = set_parameters()
    headers = set_headers(token)
    body = define_body()

    response = send_post_request(url, headers, params, body)

    if response.status_code == 200:
        print("Response:", response.json())
    else:
        print("Request failed with status code:", response.status_code)
        print("Error message:", response.text)


if __name__ == "__main__":
    main()
