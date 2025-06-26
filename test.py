import json
import requests

with open('config.json') as f:
    config = json.load(f)

instance1 = config['instances']['instance1']

# Test query on one table
url = f"https://{instance1['host']}.service-now.com/api/now/table/sys_ui_action"
print(config['query'])
params = {
    "sysparm_query": config['query'],
    "sysparm_limit": "10"
}
resp = requests.get(
    url, auth=(instance1['user'], instance1['pass']), params=params
)
resp.raise_for_status()
print(resp.json())  # Print the raw JSON
print("Count:", len(resp.json().get('result', [])))
