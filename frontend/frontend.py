import requests
import streamlit as st
import uuid
import json

user_id = str(uuid.uuid1())

def get_response_from_api(prompt_text):
    url = "https://docmorris_chatbot-timely-springhare-yj.cfapps.eu10-004.hana.ondemand.com/ask_chatbot"
    payload = {
        "prompt": prompt_text,
        "session_id": user_id
    }
    headers = {
        "Content-Type": "application/json"
    }
    
    response = requests.post(url, headers=headers, data=json.dumps(payload), verify=False)
    
    if response.status_code == 200:
        return response.json().get('content', 'No response received')
    else:
        return f"Error: {response.status_code}, {response.text}"

def main():
    st.title("DocMorris - Where's my package?")
    st.logo("logo.jpg")

    user_prompt = st.text_input("Enter your prompt:")
    submit_button = st.button("Get Response")

    if submit_button and user_prompt:
        with st.spinner("Generating response... Please wait."):
            response = get_response_from_api(user_prompt)
        st.success("Response generated successfully!")
        st.write(response)

if __name__ == "__main__":
    main()
