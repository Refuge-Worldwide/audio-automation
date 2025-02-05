import os
import requests

def send_error_to_slack(text):
    slack_url = os.getenv('SLACK_ERROR_URL')
    if not slack_url:
        raise ValueError("SLACK_ERROR_URL environment variable not set")
    
    payload = {
        "text": "(っ˘̩╭╮˘̩)っ Audio automation error (｡•́︿•̀｡)\n\n" + text
    }
    
    response = requests.post(slack_url, json=payload)
    
    if response.status_code != 200:
        raise ValueError(f"Request to Slack returned an error {response.status_code}, the response is:\n{response.text}")