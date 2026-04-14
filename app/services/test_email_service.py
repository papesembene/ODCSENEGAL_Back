import os
import logging
from flask import current_app, render_template_string
from flask_mail import Message

class TestEmailService:
    def __init__(self):
        # On utilise la configuration de Flask-Mail via current_app
        # Pas besoin de variables SendGrid ici
        pass

    def send_test_invitation(self, 
                             candidate_email, 
                             candidate_name, 
                             candidate_phone,
                             test_title, 
                             test_date, 
                             test_time, 
                             test_duration,
                             test_link,
                             candidate_gender=None):
        
        try:
            # URL de ton logo hébergé
            logo_url = "https://orangedigitalcenter.sn/Logotest.png"
            
            # Déterminer la terminaison selon le genre
            if candidate_gender:
                gender_lower = candidate_gender.lower()
                if gender_lower in ['f', 'femme', 'female', 'femenin', 'féminin']:
                    greeting_suffix = "e"
                else:
                    greeting_suffix = ""
            else:
                greeting_suffix = "(e)"

            # Contenu HTML (identique à l'original)
            html_content = f"""
                <!DOCTYPE html>
                <html lang="fr">
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <style>
                        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
                        .email-container {{ max-width: 600px; margin: 0 auto; background-color: #ffffff; border: 1px solid #eee; }}
                        .logo-section {{ text-align: center; padding: 20px; }}
                        .main-content {{ padding: 20px 30px; text-align: center; }}
                        .greeting {{ font-size: 24px; font-weight: 700; color: #333; margin-bottom: 20px; }}
                        .button {{ display: inline-block; padding: 14px 35px; background-color: #ff6600; color: #000; text-decoration: none; border-radius: 6px; font-weight: 700; margin: 25px 0; }}
                        .credentials-section {{ border: 2px solid #ff6600; border-radius: 8px; padding: 20px; text-align: left; margin: 20px 0; }}
                        .detail-item {{ margin-bottom: 10px; font-size: 15px; }}
                        .detail-label {{ font-weight: 700; color: #333; }}
                        .credential-value {{ color: #ff6600; font-weight: 700; }}
                        .footer {{ background-color: #f8f9fa; padding: 20px; text-align: center; font-size: 12px; color: #6c757d; border-top: 1px solid #dee2e6; }}
                    </style>
                </head>
                <body>
                    <div class="email-container">
                        <div class="logo-section">
                            <img src="{logo_url}" alt="Logo" width="200" style="max-width: 200px;" />
                        </div>
                        <div class="main-content">
                            <h1 class="greeting">Merci de vous être inscrit{greeting_suffix}, {candidate_name} !</h1>
                            <p>Votre session de test a été reprogrammée. Merci de vous connecter à l'heure indiquée ci-dessous.</p>
                            
                            <div class="credentials-section">
                                <h3 style="color: #ff6600; margin-bottom: 15px;">Détails du Test</h3>
                                <div class="detail-item"><span class="detail-label">Titre :</span> {test_title}</div>
                                <div class="detail-item"><span class="detail-label">Date :</span> {test_date}</div>
                                <div class="detail-item"><span class="detail-label">Heure :</span> {test_time}</div>
                                <div class="detail-item"><span class="detail-label">Durée :</span> {test_duration} minutes</div>
                                
                                <h3 style="color: #ff6600; margin-top: 20px; margin-bottom: 15px;">Vos Identifiants</h3>
                                <div class="detail-item"><span class="detail-label">Email :</span> <span class="credential-value">{candidate_email}</span></div>
                                <div class="detail-item"><span class="detail-label">Téléphone :</span> <span class="credential-value">{candidate_phone}</span></div>
                                
                                <div style="text-align: center; margin-top: 20px;">
                                    <a href="{test_link}" class="button">Accéder au Test</a>
                                </div>
                            </div>
                        </div>
                        <div class="footer">
                            <p><strong>Cet email est automatique, merci de ne pas y répondre.</strong></p>
                            <p>Orange Digital Center - Sonatel</p>
                        </div>
                    </div>
                </body>
                </html>
            """
            
            # Utilisation de Flask-Mail
            from app import mail as flask_mail_instance
            
            msg = Message(
                subject=f"Invitation au test – {test_title}",
                recipients=[candidate_email],
                html=html_content,
                sender=current_app.config.get('MAIL_DEFAULT_SENDER', 'orangedigitalcenter@orange-sonatel.com')
            )
            
            # On utilise l'instance globale mail initialisée dans __init__.py
            flask_mail_instance.send(msg)
            logging.info(f"✅ Email envoyé à {candidate_email} via Flask-Mail")
            return True

        except Exception as e:
            logging.error(f"❌ Erreur lors de l'envoi de l'email à {candidate_email}: {str(e)}")
            return False

    def send_bulk_invitations(self, candidates, test_title, test_date, test_time, test_duration, test_link):
        sent = 0
        failed = 0
        failed_emails = []
        
        for candidate in candidates:
            try:
                if self.send_test_invitation(
                    candidate_email=candidate.email,
                    candidate_name=f"{candidate.first_name} {candidate.last_name}",
                    candidate_phone=getattr(candidate, 'phone', 'Non renseigné'),
                    test_title=test_title,
                    test_date=test_date,
                    test_time=test_time,
                    test_duration=test_duration,
                    test_link=test_link,
                    candidate_gender=getattr(candidate, 'gender', None)
                ):
                    sent += 1
                else:
                    failed += 1
                    failed_emails.append(candidate.email)
            except Exception as e:
                failed += 1
                failed_emails.append(getattr(candidate, 'email', 'unknown'))
                
        return {
            'success': failed == 0,
            'sent': sent,
            'failed': failed,
            'failed_emails': failed_emails,
            'total': len(candidates)
        }