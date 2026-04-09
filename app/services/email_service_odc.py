# backend\app\services\email_service.py

from flask import current_app, render_template_string
from flask_mail import Mail, Message

class EmailService:
    def __init__(self, app=None):
        self.mail = None
        if app:
            self.init_app(app)

    def init_app(self, app):
        self.mail = Mail(app)

    def send_confirmation_email(self, candidate_data):
        """Envoyer un email de confirmation de candidature à une formation ODC"""
        try:
            subject = "Confirmation de votre candidature - Formation ODC"
            recipient = candidate_data['email']

            html_template = """
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <title>Confirmation de candidature ODC</title>
                <style>
                        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
                        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
                        .header { background-color: #ff6600; color: white; padding: 20px; text-align: center; border-radius: 8px 8px 0 0; }
                        .content { padding: 20px; background-color: #f9f9f9; }
                        .footer { padding: 20px; text-align: center; font-size: 12px; color: #666; background-color: #e9e9e9; border-radius: 0 0 8px 8px; }
                        .info-box { background-color: white; padding: 15px; margin: 10px 0; border-radius: 5px; border-left: 4px solid #ff6600; }
                        .warning { background-color: #fff3cd; padding: 10px; border-radius: 5px; border: 1px solid #ffeaa7; margin: 15px 0; }
                        ul { padding-left: 20px; }
                        li { margin-bottom: 8px; }
                    </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1>Orange Digital Center</h1>
                        <h2>Confirmation de votre candidature</h2>
                    </div>

                    <div class="content">
                        <p>Bonjour <strong>{{ firstName }} {{ lastName }}</strong>,</p>

                        <p>Nous avons bien reçu votre candidature à la formation <strong>{{ formation }}</strong>.</p>

                        <div class="info-box">
                            <h3>📋 Détails de votre candidature :</h3>
                            <p><strong>Formation choisie :</strong> {{ formation }}</p>
                            <p><strong>Date de soumission :</strong> {{ submissionDate }}</p>
                        </div>

                        <p>Notre équipe pédagogique va examiner votre dossier sous peu. Vous recevrez un email de notre part si vous êtes présélectionné(e) pour cette session.</p>

                        <p>Merci pour votre intérêt pour nos formations.<br><br>
                        <strong>L’équipe ODC</strong></p>
                    </div>

                    <div class="footer">
                        ⚠️ Cet email a été envoyé automatiquement. Ne pas y répondre.<br>
                        Contact : contact@odc.sn<br>
                        Orange Digital Center - VDN, Dakar, Sénégal
                    </div>
                </div>
            </body>
            </html>
            """

            template_data = {
                'firstName': candidate_data.get('firstName', ''),
                'lastName': candidate_data.get('lastName', ''),
                'formation': candidate_data.get('formation', ''),
                'submissionDate': candidate_data.get('created_at', '').strftime('%d/%m/%Y à %H:%M') if candidate_data.get('created_at') else '',
            }

            html_body = render_template_string(html_template, **template_data)

            msg = Message(
                subject=subject,
                recipients=[recipient],
                html=html_body,
                sender=current_app.config['MAIL_DEFAULT_SENDER'],
                reply_to="noreply@odc.sn"
            )

            msg.extra_headers = {
                'Auto-Submitted': 'auto-generated',
                'X-Auto-Response-Suppress': 'All',
                'Precedence': 'bulk'
            }

            self.mail.send(msg)
            return True

        except Exception as e:
            print(f"Erreur lors de l'envoi de l'email: {e}")
            return False

    def send_admin_notification(self, candidate_data):
        """Notifier l’admin ODC d’une nouvelle candidature"""
        try:
            subject = f"📝 Nouvelle candidature à la formation ODC - {candidate_data.get('firstName', '')} {candidate_data.get('lastName', '')}"
            recipient = current_app.config.get('ADMIN_EMAIL', current_app.config['MAIL_DEFAULT_SENDER'])

            html_template = """
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <style>
                        body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
                        .container { max-width: 600px; margin: 0 auto; padding: 20px; }
                        .header { background-color: #ff6600; color: white; padding: 15px; border-radius: 5px; }
                        .content { padding: 20px; background-color: #f9f9f9; margin-top: 10px; border-radius: 5px; }
                        .info-row { margin: 8px 0; }
                        .label { font-weight: bold; color: #ff6600; }
                    </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h2>📩 Nouvelle candidature à une formation ODC</h2>
                    </div>

                    <div class="content">
                        <div class="info-row">
                            <span class="label">👤 Candidat :</span> {{ firstName }} {{ lastName }}
                        </div>
                        <div class="info-row">
                            <span class="label">📧 Email :</span> {{ email }}
                        </div>
                        <div class="info-row">
                            <span class="label">🎓 Formation :</span> {{ formation }}
                        </div>
                        <div class="info-row">
                            <span class="label">📅 Date de soumission :</span> {{ submissionDate }}
                        </div>

                        <p style="margin-top: 20px; padding: 15px; background-color: #e8f4fd; border-radius: 5px;">
                            Connectez-vous à l'interface admin pour valider ou rejeter cette candidature.
                        </p>
                    </div>
                </div>
            </body>
            </html>
            """

            template_data = {
                'firstName': candidate_data.get('firstName', ''),
                'lastName': candidate_data.get('lastName', ''),
                'email': candidate_data.get('email', ''),
                'formation': candidate_data.get('formation', ''),
                'submissionDate': candidate_data.get('created_at', '').strftime('%d/%m/%Y à %H:%M') if candidate_data.get('created_at') else '',
            }

            html_body = render_template_string(html_template, **template_data)

            msg = Message(
                subject=subject,
                recipients=[recipient],
                html=html_body,
                sender=current_app.config['MAIL_DEFAULT_SENDER']
            )

            self.mail.send(msg)
            return True

        except Exception as e:
            print(f"Erreur lors de l'envoi de la notification admin: {e}")
            return False
