import csv
import pymongo
from datetime import datetime

# Connexion à MongoDB (en local ici)
client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["odcdb"]
collection = db["candidatures"]

# Fichier CSV à importer
csv_file_path = "C:\Users\stg_kebe89654\OneDrive - Orange Sonatel\Documents\ODC SOURCING\candidatures_refdig-2025-04-30.csv"

with open(csv_file_path, newline='', encoding='utf-8') as csvfile:
    reader = csv.DictReader(csvfile)
    documents = []
    for row in reader:
        doc = {
            "last_name": row["Nom"].strip(),
            "first_name": row["Prénom"].strip(),
            "date_of_birth": datetime.strptime(row["Date de Naissance "].strip(), "%Y-%m-%d"),
            "place_of_birth": row["Lieu de naissance "].strip(),
            "gender": row["Genre"].strip(),
            "nationality": row["Nationalité"].strip(),
            "cni_or_passport_number": row["N° CNI ou Passeport"].strip(),
            "region_of_residence": row["Region de Residence"].strip(),
            "email": row["Email"].strip(),
            "phone": row["Téléphone"].strip(),
            "education_level": row["Niveau d’étude "].strip(),
            "current_structure": row["Structure actuelle (université, lycée, école de formation) ?"].strip(),
            "speciality": row["Spécialité (faculté, ufr, série…) ?"].strip(),
            "computer_skills": row["As-tu des notions en informatique ?"].strip(),
            "currently_working": row["Travailles-tu dans une entreprise actuellement ?"].strip(),
            "contract_type": row["Si oui,quel type de contrat ? <span style=\"color:grey; font-size:12px\">(si non laisser ce champ vide)<\/span>"].strip(),
            "available_for_10_months": row["Es-tu dispo pour te consacrer exclusivement à la formation pendant une période de <span style=\"text-decoration:underline\">10 mois <\/span>à compter de janvier 2025 "].strip(),
            "form_name": row["Form Name (ID)"].strip(),
            "submission_id": int(row["Submission ID"]),
            "created_at": datetime.strptime(row["Created At"].strip(), "%Y-%m-%d %H:%M:%S"),
            "user_id": row["User ID"].strip(),
            "user_agent": row["User Agent"].strip(),
            "user_ip": row["User IP"].strip(),
            "referrer": row["Referrer"].strip()
        }
        documents.append(doc)

# Insertion dans MongoDB
if documents:
    result = collection.insert_many(documents)
    print(f"{len(result.inserted_ids)} candidatures importées avec succès.")
else:
    print("Aucune donnée à importer.")
