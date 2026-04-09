# backend\app\services\email_service.py

from flask import current_app, render_template_string
from flask_mail import Mail, Message
import os

class EmailService:
    def __init__(self, app=None):
        self.mail = None
        if app:
            self.init_app(app)
    
    def init_app(self, app):
        self.mail = Mail(app)
    
    def send_confirmation_email(self, candidate_data):
        """Envoyer un email de confirmation de candidature"""
        try:
            subject = "Confirmation de votre candidature Orange Fab"
            recipient = candidate_data['email']
            
            # Template HTML pour l'email
            html_template = """
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <title>Confirmation de candidature</title>
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
                        <h1>Orange Fab</h1>
                        <h2>Confirmation de candidature</h2>
                    </div>
                    
                    <div class="content">
                        <p>Bonjour <strong>{{ firstName }} {{ lastName }}</strong>,</p>
                        
                        <p>Nous avons bien reçu votre candidature pour le programme Orange Fab. Merci pour votre intérêt et votre confiance !</p>
                        
                        <div class="info-box">
                            <h3>📋 Récapitulatif de votre candidature :</h3>
                            <p><strong>Nom de l'entreprise :</strong> {{ companyName }}</p>
                            <p><strong>Secteur d'activité :</strong> {{ sector }}</p>
                            <p><strong>Produit/Service :</strong> {{ productName }}</p>
                            <p><strong>Date de soumission :</strong> {{ submissionDate }}</p>
                        </div>
                        
                        <div class="info-box">
                            <h3>🚀 Prochaines étapes :</h3>
                            <ul>
                                <li><strong>Examen du dossier :</strong> Notre équipe va examiner votre candidature dans les 5 à 7 jours ouvrables</li>
                                <li><strong>Notification :</strong> Vous recevrez un email de notre part avec la suite du processus</li>
                                <li><strong>Entretien :</strong> Si votre candidature est retenue, nous vous contacterons pour un entretien</li>
                                <li><strong>Sélection finale :</strong> Les candidats retenus seront intégrés au programme Orange Fab</li>
                            </ul>
                        </div>
                        
                        <p>Si vous avez des questions concernant votre candidature, n'hésitez pas à nous contacter à l'adresse : <a href="mailto:contact@orangefab.sn">contact@orangefab.sn</a> en mentionnant votre numéro de référence.</p>
                        
                        <p>Nous vous remercions encore pour votre candidature et vous souhaitons bonne chance pour la suite du processus de sélection.</p>
                        
                        <p>Cordialement,<br><strong>L'équipe Orange Fab</strong><br>Programme d'accélération de startups</p>
                    </div>
                    
                    <div class="footer">
                        <p><strong>⚠️ Cet email a été envoyé automatiquement, merci de ne pas y répondre directement.</strong></p>
                        <p>Pour toute question, utilisez l'adresse : contact@orangefab.sn</p>
                        <p>Orange Fab - Programme d'accélération de startups | Sonatel</p>
                        <p>64, Voie de Dégagement Nord (VDN), Dakar, Sénégal</p>
                    </div>
                </div>
            </body>
            </html>
            """
            
            # Préparer les données pour le template
            template_data = {
                'firstName': candidate_data.get('firstName', ''),
                'lastName': candidate_data.get('lastName', ''),
                'companyName': candidate_data.get('companyName', ''),
                'sector': candidate_data.get('sector', ''),
                'productName': candidate_data.get('productName', ''),
                'submissionDate': candidate_data.get('created_at', '').strftime('%d/%m/%Y à %H:%M') if candidate_data.get('created_at') else '',
            }
            
            html_body = render_template_string(html_template, **template_data)
            
            # Créer et envoyer le message avec en-têtes pour empêcher les réponses
            msg = Message(
                subject=subject,
                recipients=[recipient],
                html=html_body,
                sender=current_app.config['MAIL_DEFAULT_SENDER'],
                reply_to="noreply@orangefab.sn"  # Adresse de non-réponse
            )
            
            # Ajouter des en-têtes pour empêcher les réponses automatiques
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
        """Envoyer une notification à l'admin"""
        try:
            subject = f"🔔 Nouvelle candidature Orange Fab - {candidate_data.get('companyName', 'N/A')}"
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
                        <h2>🔔 Nouvelle candidature Orange Fab</h2>
                    </div>
                    
                    <div class="content">
                        <div class="info-row">
                            <span class="label">👤 Candidat :</span> {{ firstName }} {{ lastName }}
                        </div>
                        <div class="info-row">
                            <span class="label">📧 Email :</span> {{ email }}
                        </div>
                        <div class="info-row">
                            <span class="label">🏢 Entreprise :</span> {{ companyName }}
                        </div>
                        <div class="info-row">
                            <span class="label">🏭 Secteur :</span> {{ sector }}
                        </div>
                        <div class="info-row">
                            <span class="label">🚀 Produit :</span> {{ productName }}
                        </div>
                        <div class="info-row">
                            <span class="label">📅 Date :</span> {{ submissionDate }}
                        </div>
                        
                        <p style="margin-top: 20px; padding: 15px; background-color: #e8f4fd; border-radius: 5px;">
                            <strong>Action requise :</strong> Connectez-vous à l'interface d'administration pour examiner cette candidature en détail.
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
                'companyName': candidate_data.get('companyName', ''),
                'sector': candidate_data.get('sector', ''),
                'productName': candidate_data.get('productName', ''),
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