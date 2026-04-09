import os
import logging
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Content
import certifi


os.environ['SSL_CERT_FILE'] = certifi.where()

class TestEmailService:
    def __init__(self):
        self.sendgrid_api_key = os.getenv("SENDGRID_API_KEY")
        self.from_email = os.getenv("SENDGRID_FROM_EMAIL", "orangedigitalcenter@orange-sonatel.com")
        self.frontend_url = os.getenv("FRONTEND_URL", "https://orangedigitalcenter.sn")
       
        
        if not self.sendgrid_api_key:
            logging.warning("⚠️ SENDGRID_API_KEY non configurée. Les emails ne seront pas envoyés.")

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
                    greeting_suffix = "e"  # "inscrite"
                    invitation_suffix = "e"  # "invitée"
                else:
                    greeting_suffix = ""  # "inscrit"
                    invitation_suffix = ""  # "invité"
            else:
                # Par défaut, utiliser (e) si le genre n'est pas disponible
                greeting_suffix = "(e)"
                invitation_suffix = "(e)"

            # ================================
            # TEMPLATE HTML DE L'EMAIL
            # ================================
            html_content = f"""
                <!DOCTYPE html>
                <html lang="fr">
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <style>
                        * {{
                            margin: 0;
                            padding: 0;
                            box-sizing: border-box;
                        }}

                        body {{
                            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
                            background-color: #f5f5f5;
                            color: #333;
                            line-height: 1.6;
                        }}

                        .email-wrapper {{
                            padding: 40px 20px;
                            background-color: #f5f5f5;
                        }}

                        .email-container {{
                            max-width: 600px;
                            margin: 0 auto;
                            background-color: #ffffff;
                        }}

                        .logo-section {{
                            text-align: center;
                            padding: 20px 20px 10px;
                            background-color: #ffffff;
                        }}

                        .logo-section img {{
                            max-width: 200px;
                            width: 200px;
                            height: auto;
                            display: block;
                            margin: 0 auto 5px;
                            border: 0;
                            outline: none;
                        }}

                        .brand-name {{
                            color: #333;
                            font-size: 24px;
                            font-weight: 700;
                            text-decoration: none;
                            border-bottom: 3px solid #ff6600;
                            display: inline-block;
                            padding-bottom: 5px;
                        }}

                        .main-content {{
                            padding: 20px 30px 40px;
                            background-color: #ffffff;
                            text-align: center;
                        }}

                        .greeting {{
                            font-size: 32px;
                            font-weight: 700;
                            color: #333;
                            margin-bottom: 20px;
                            margin-top: 0;
                            line-height: 1.2;
                        }}

                        .instruction-text {{
                            font-size: 16px;
                            color: #555;
                            margin-bottom: 15px;
                            line-height: 1.6;
                        }}

                        .thank-you {{
                            font-size: 18px;
                            color: #ff6600;
                            font-weight: 600;
                            margin: 20px 0;
                        }}

                        .button {{
                            display: inline-block;
                            padding: 14px 35px;
                            background-color: #ff6600;
                            color: #000000;
                            text-decoration: none;
                            border-radius: 6px;
                            font-weight: 700;
                            font-size: 16px;
                            margin: 25px 0;
                            transition: background-color 0.3s ease, color 0.3s ease;
                        }}
                        .button:hover {{
                            background-color: #000000;
                            color: #ffffff;
                        }}

                        .details-section {{
                            background-color: #ffffff;
                            padding: 25px 0;
                            text-align: left;
                            margin: 20px 0;
                        }}

                        .section-title {{
                            font-size: 18px;
                            font-weight: 700;
                            color: #ff6600;
                            margin-bottom: 20px;
                            text-align: left;
                            padding-bottom: 8px;
                            border-bottom: 1px solid #ff6600;
                        }}

                        .credentials-section {{
                            background-color: #ffffff;
                            border: 2px solid #ff6600;
                            border-radius: 8px;
                            padding: 30px;
                            margin: 30px 0;
                            text-align: left;
                            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
                        }}


                        .detail-item {{
                            margin-bottom: 12px;
                            font-size: 15px;
                        }}

                        .detail-label {{
                            font-weight: 700;
                            color: #333;
                        }}

                        .detail-value {{
                            color: #333;
                            font-weight: 500;
                        }}

                        .detail-link {{
                            color: #ff6600;
                            text-decoration: underline;
                            font-weight: 600;
                        }}

                        .credential-value {{
                            color: #ff6600;
                            font-weight: 700;
                            font-size: 16px;
                        }}

                        .info-section {{
                            background-color: #2c2c2c;
                            color: #ffffff;
                            padding: 40px 30px;
                        }}

                        .info-section-title {{
                            font-size: 20px;
                            font-weight: 700;
                            margin-bottom: 25px;
                            text-align: center;
                        }}

                        .info-list {{
                            list-style: none;
                            padding: 0;
                            margin: 0;
                        }}

                        .info-list li {{
                            font-size: 15px;
                            line-height: 1.8;
                            margin-bottom: 15px;
                            padding-left: 25px;
                            position: relative;
                        }}

                        .info-list li:before {{
                            content: counter(item);
                            counter-increment: item;
                            position: absolute;
                            left: 0;
                            color: #ff6600;
                            font-weight: 700;
                        }}

                        .info-list {{
                            counter-reset: item;
                        }}

                        .warning {{
                            background-color: #fff3cd;
                            border-left: 4px solid #ffc107;
                            padding: 15px 20px;
                            border-radius: 4px;
                            margin: 25px 0;
                            font-size: 14px;
                            color: #856404;
                            line-height: 1.6;
                        }}

                        .warning strong {{
                            color: #856404;
                            font-weight: 700;
                        }}

                        .more-info {{
                            color: #ff6600;
                            font-weight: 600;
                            margin-top: 20px;
                            text-align: center;
                            font-size: 16px;
                        }}

                        .support-section {{
                            text-align: center;
                            color: #ffffff;
                            margin-top: 25px;
                            font-size: 15px;
                        }}

                        .support-button {{
                            display: inline-block;
                            padding: 14px 35px;
                            background-color: #ff6600;
                            color: #ffffff;
                            text-decoration: none;
                            border-radius: 6px;
                            font-weight: 700;
                            font-size: 16px;
                            margin-top: 20px;
                        }}

                        .footer {{
                            background-color: #f8f9fa;
                            padding: 25px 30px;
                            text-align: center;
                            border-top: 1px solid #dee2e6;
                        }}

                        .footer p {{
                            font-size: 12px;
                            color: #6c757d;
                            margin-bottom: 8px;
                        }}

                        @media only screen and (max-width: 600px) {{
                            .email-wrapper {{
                                padding: 20px 10px;
                            }}

                            .main-content {{
                                padding: 30px 20px !important;
                            }}

                            .info-section {{
                                padding: 30px 20px !important;
                            }}

                            .greeting {{
                                font-size: 24px !important;
                            }}
                        }}
                    </style>
                </head>

                <body>
                <div class="email-wrapper">
                    <div class="email-container">

                        <!-- Logo Section -->
                        <div class="logo-section">
                            <img src="{logo_url}" alt="Orange Digital Center Logo" width="200" style="max-width: 200px; width: 200px; height: auto; display: block; margin: 0 auto 15px; border: 0; outline: none; text-decoration: none;" />
                        </div>

                        <!-- Main Content Section (White Background) -->
                        <div class="main-content">
                            <h1 class="greeting">Merci de vous être inscrit{greeting_suffix}, {candidate_name} !</h1>

                            <p class="instruction-text">
                            
                                <strong>Information importante :</strong> suite aux désagréments rencontrés, votre groupe est reprogrammé.
                                Nous vous prions de nous excuser pour la gêne occasionnée. <br/>
                                Merci de vous connecter <strong>à l'heure indiquée ci-dessous</strong> et de suivre attentivement les consignes.
                            </p>

                            <!-- Détails du Test et Identifiants de Connexion -->
                            <div class="credentials-section">
                                <h3 class="section-title">Détails du Test</h3>
                                
                                <div class="detail-item">
                                    <span class="detail-label">Titre :</span>
                                    <span class="detail-value">{test_title}</span>
                                </div>

                                <div class="detail-item">
                                    <span class="detail-label">Date :</span>
                                    <span class="detail-value">{test_date}</span>
                                </div>

                                <div class="detail-item">
                                    <span class="detail-label">Heure :</span>
                                    <span class="detail-value">{test_time}</span>
                                </div>

                                <div class="detail-item">
                                    <span class="detail-label">Durée :</span>
                                    <span class="detail-value">{test_duration} minutes</span>
                                </div>

                                <div style="margin: 30px 0; height: 1px; background-color: #ffe0cc;"></div>

                                <h3 class="section-title" style="margin-top: 25px;">Vos Identifiants de Connexion</h3>
                                
                                <p style="margin-bottom: 25px; color: #555; font-size: 14px; line-height: 1.6;">
                                    Utilisez ces identifiants pour vous connecter au test. Conservez-les jusqu'à la fin de votre test.
                                </p>

                                <div class="detail-item" style="margin-bottom: 15px;">
                                    <span class="detail-label">Email :</span>
                                    <span class="credential-value">{candidate_email}</span>
                                </div>

                                <div class="detail-item" style="margin-bottom: 15px;">
                                    <span class="detail-label">Téléphone :</span>
                                    <span class="credential-value">{candidate_phone}</span>
                                </div>

                                <div style="margin-top: 30px; padding-top: 25px; border-top: 1px solid #ffe0cc; text-align: center;">
                                    <a href="{test_link}" class="button">Accéder au Test</a>
                                </div>
                            </div>


                            <div class="warning">
                                <strong>Important :</strong>
                               Le test est soumis à un dispositif de surveillance. Toute tentative de fraude est automatiquement détectée, consignée et communiquée à l’équipe d’évaluation, pouvant entraîner l’invalidation du test.
                            </div>
                        </div>

                        <!-- Footer -->
                        <div class="footer">
                            <p><strong>Cet email a été envoyé automatiquement, merci de ne pas y répondre directement.</strong></p>
                            <p>Orange Digital Center - Sonatel</p>
                            <p>+221 33 839 21 00</p>
                            <p>64, Voie de Dégagement Nord (VDN), Dakar, Sénégal</p>
                        </div>

                    </div>
                </div>
                </body>
                </html>
            """
            # ================================
            # ENVOI VIA SENDGRID
            # ================================
            if not self.sendgrid_api_key:
                logging.error(f"⚠️ SendGrid non configuré. Email non envoyé à {candidate_email}")
                return False
            
            message = Mail(
                from_email=Email(self.from_email, "Orange Digital Center"),
                to_emails=To(candidate_email),
                subject=f"Invitation au test – {test_title}",
                html_content=Content("text/html", html_content)
            )

            sg = SendGridAPIClient(self.sendgrid_api_key)
            response = sg.send(message)

            if response.status_code in [200, 201, 202]:
                logging.info(f"✅ Email envoyé à {candidate_email} — Statut {response.status_code}")
                return True
            else:
                logging.error(f"❌ Erreur SendGrid pour {candidate_email}: Status {response.status_code} - {response.body}")
                return False

        except Exception as e:
            error_msg = str(e)
            logging.error(f"❌ Erreur lors de l'envoi de l'email à {candidate_email}: {error_msg}")
            # Afficher plus de détails pour les erreurs 403
            if "403" in error_msg or "Forbidden" in error_msg:
                logging.error("💡 Vérifiez que:")
                logging.error("   1. L'API key SendGrid est valide et a les permissions 'Mail Send'")
                logging.error(f"   2. L'adresse email '{self.from_email}' est vérifiée dans SendGrid")
                logging.error("   3. Le domaine est vérifié dans SendGrid (si vous utilisez un domaine personnalisé)")
            return False

    def send_bulk_invitations(self, candidates, test_title, test_date, test_time, test_duration, test_link):
        """
        Envoyer des invitations en masse à plusieurs candidats
        """
        if not self.sendgrid_api_key:
            logging.error("SENDGRID_API_KEY non configurée")
            return {
                'success': False,
                'sent': 0,
                'failed': len(candidates) if candidates else 0,
                'failed_emails': [],
                'total': len(candidates) if candidates else 0
            }
        
        if not candidates:
            return {
                'success': True,
                'sent': 0,
                'failed': 0,
                'failed_emails': [],
                'total': 0
            }
        
        sent = 0
        failed = 0
        failed_emails = []
        total = len(candidates)
        
        logging.info(f"Début de l'envoi de {total} invitations...")
        
        for candidate in candidates:
            try:
                candidate_email = candidate.email
                candidate_name = f"{candidate.first_name} {candidate.last_name}"
                candidate_phone = getattr(candidate, 'phone', 'Non renseigné')
                candidate_gender = getattr(candidate, 'gender', None)
                
                if self.send_test_invitation(
                    candidate_email=candidate_email,
                    candidate_name=candidate_name,
                    candidate_phone=candidate_phone,
                    candidate_gender=candidate_gender,
                    test_title=test_title,
                    test_date=test_date,
                    test_time=test_time,
                    test_duration=test_duration,
                    test_link=test_link
                ):
                    sent += 1
                else:
                    failed += 1
                    failed_emails.append(candidate_email)
                    
            except Exception as e:
                logging.error(f"Erreur pour le candidat {getattr(candidate, 'email', 'inconnu')}: {str(e)}")
                failed += 1
                if hasattr(candidate, 'email'):
                    failed_emails.append(candidate.email)
        
        logging.info(f"Envoi terminé: {sent} succès, {failed} échecs sur {total} candidats")
        
        return {
            'success': failed == 0,
            'sent': sent,
            'failed': failed,
            'failed_emails': failed_emails,
            'total': total
        }