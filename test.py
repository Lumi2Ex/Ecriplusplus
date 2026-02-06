import json

def format(string:str) -> str:
    while string.find(">") >= 0:
        balise = string[string.find("<"):string.find(">")+1]
        print(f"Found balise : {balise}. At idx {string.find("<")}. Deleting")

        if balise == "<br/>" or balise == "<br>" :
            string = string.replace(str(balise), "\n", 1)
        else :
            string = string.replace(str(balise), "", 1)
    
    return string


def parse_request(raw_request) -> dict:

    formated_request = json.loads(raw_request)

    raw_question = formated_request["log"]["entries"][0]["response"]["content"]["text"]

    response = json.loads(raw_question)

    question = {
        "title": "",
        "type": "",
        "format": "",
        "instruction": "",
        "proposals": "",
        "explication": ""
    }


    question["title"] = str(response["data"]["attributes"]["title"])
    question["type"] = str(response["data"]["attributes"]["type"])
    question["format"] = str(response["data"]["attributes"]["format"])
    question["instruction"] = format(response["data"]["attributes"]["instruction"])
    question["proposals"] = format(response["data"]["attributes"]["proposals"])
    question["explication"] = format(response["data"]["attributes"]["explication"])

    return question



# Lire la requête depuis le fichier
with open("har requests/app.tests.ecriplus.fr_api_assessments_3538400_next_Archive [26-02-06 19-37-56].har", "r", encoding="utf-8") as f:
    request = f.read()

# Récupérer les informations relative à la question
parsed_request = parse_request(request)

# Écrire la question formatée dans un ficheir
with open("har requests/formatted_next.json", "w", encoding="utf-8") as f:
    f.write(json.dumps(parsed_request, indent=4, ensure_ascii=False))


print("Done !")