import os
import requests

def send_error_to_slack(text):
    slack_url = os.getenv('SLACK_ERROR_URL')
    if not slack_url:
        print(f"Slack notifications disabled. Error: {text}")
        return
    
    payload = {
        "text": "(っ˘̩╭╮˘̩)っ Audio automation error (｡•́︿•̀｡)\n\n" + text
    }
    
    try:
        response = requests.post(slack_url, json=payload)
        
        if response.status_code != 200:
            print(f"Failed to send to Slack: {response.status_code}, {response.text}")
    except Exception as e:
        print(f"Error sending to Slack: {e}")