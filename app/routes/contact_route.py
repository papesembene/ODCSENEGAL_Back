from flask import Blueprint, request, jsonify
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os

contact_bp = Blueprint('contact', __name__)

@contact_bp.route("/", methods=["POST", "OPTIONS"])
def contact():
    # Gestion de la requête OPTIONS (preflight CORS)
    if request.method == 'OPTIONS':
        return '', 200

    data = request.get_json()
    print("Formulaire reçu :", data)

    name = data.get("name")
    email = data.get("email")
    phone = data.get("phone")
    subject = data.get("subject")
    message = data.get("message")
    contact_pref = data.get("contactPreference")

    email_subject = f"Nouveau message de contact - {subject}"
    email_body = f"""
Nom: {name}
Email: {email}
Téléphone: {phone}
Préférence de contact: {contact_pref}

Message:
{message}
"""

    try:
        sender_email = os.getenv("MAIL_USERNAME", "babakargueye05@gmail.com")
        sender_password = os.getenv("MAIL_PASSWORD", "tppuxwjnigubwyuj")
        recipient_email = "thiernohamidou.balde@orange-sonatel.com"

        msg = MIMEMultipart()
        msg["From"] = sender_email
        msg["To"] = recipient_email
        msg["Subject"] = email_subject
        msg.attach(MIMEText(email_body, "plain"))

        # Option 1: SMTP avec STARTTLS sur port 587
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.ehlo()
            server.starttls()
            print("SMTP LOGIN:", sender_email[:3] + "***", bool(sender_password))
            server.login(sender_email, sender_password)
            server.send_message(msg)

        return jsonify({"message": "Message envoyé avec succès"}), 200

    except Exception as e:
        print("Erreur lors de l'envoi de l'email :", str(e))
        return jsonify({"error": f"Échec de l'envoi de l'email: {str(e)}"}), 500
