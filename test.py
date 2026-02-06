import json

with open("har requests/app.tests.ecriplus.fr_api_assessments_3538400_next_Archive [26-02-06 19-37-56].har", "r") as f:
    request = f.read()

formated = json.loads(request)

raw = formated["log"]["entries"][0]["response"]["content"]["text"]

response = json.dumps(json.loads(raw), indent=4)

with open("har requests/formatted_next.json", "w") as f:
    f.write(response)