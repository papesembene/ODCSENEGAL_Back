from flask import current_app, render_template_string
from flask_mail import Mail, Message
import os

class StartupEmailService:
    def __init__(self, app=None):
        self.mail = None
        if app:
            self.init_app(app)
    
    def init_app(self, app):
        self.mail = Mail(app)
    
    def send_confirmation_email(self, candidate_data):
        """Envoyer un email de confirmation de candidature Startup Lab"""
        try:
            subject = "Confirmation de votre candidature Startup Lab"
            recipient = candidate_data['email']
        
            # Obtenir l'expéditeur par défaut avec une valeur de fallback
            default_sender = current_app.config.get('MAIL_DEFAULT_SENDER', 'noreply@startuplab.sn')
        
            # Template HTML reste le même...
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
                .program-badge { background-color: #ff6600; color: white; padding: 5px 10px; border-radius: 15px; font-size: 12px; font-weight: bold; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🚀 Startup Lab</h1>
                    <h2>Confirmation de candidature</h2>
                    <span class="program-badge">Programme d'accompagnement</span>
                </div>
                
                <div class="content">
                    <p>Bonjour <strong>{{ firstName }} {{ lastName }}</strong>,</p>
                    
                    <p>Nous avons bien reçu votre candidature pour le programme <strong>Startup Lab</strong>. Merci pour votre intérêt et votre confiance dans notre programme d'accompagnement !</p>
                    
                    <div class="info-box">
                        <h3>📋 Récapitulatif de votre candidature :</h3>
                        <p><strong>Programme :</strong> {{ program }}</p>
                        <p><strong>Nom de l'entreprise :</strong> {{ companyName }}</p>
                        <p><strong>Secteur d'activité :</strong> {{ sector }}</p>
                        <p><strong>Produit/Service :</strong> {{ productName }}</p>
                        <p><strong>Date de soumission :</strong> {{ submissionDate }}</p>
                    </div>
                    
                    <div class="info-box">
                        <h3>🎯 À propos du Startup Lab :</h3>
                        <p>Le Startup Lab est notre programme de 6 mois destiné aux entrepreneurs en phase d'idéation et de prototypage. Nous vous accompagnons pour transformer votre idée en un projet viable et structuré.</p>
                    </div>
                    
                    <div class="info-box">
                        <h3>🚀 Prochaines étapes :</h3>
                        <ul>
                            <li><strong>Examen du dossier :</strong> Notre équipe va examiner votre candidature dans les 7 à 10 jours ouvrables</li>
                            <li><strong>Pré-sélection :</strong> Les candidatures retenues recevront un email pour la suite du processus</li>
                            <li><strong>Entretien :</strong> Présentation de votre projet devant notre comité de sélection</li>
                            <li><strong>Sélection finale :</strong> Les startups retenues intégreront le programme Startup Lab</li>
                            <li><strong>Lancement :</strong> Début de l'accompagnement avec notre équipe d'experts</li>
                        </ul>
                    </div>
                    
                    <div class="warning">
                        <p><strong>💡 Conseil :</strong> En attendant la réponse, continuez à travailler sur votre projet et préparez-vous pour un éventuel entretien en affinant votre pitch et votre business model.</p>
                    </div>
                    
                    <p>Si vous avez des questions concernant votre candidature ou le programme Startup Lab, n'hésitez pas à nous contacter à l'adresse : <a href="mailto:startuplab@contact.sn">startuplab@contact.sn</a></p>
                    
                    <p>Nous vous remercions encore pour votre candidature et vous souhaitons bonne chance pour la suite du processus de sélection.</p>
                    
                    <p>Cordialement,<br><strong>L'équipe Startup Lab</strong><br>Programme d'accompagnement des startups</p>
                </div>
                
                <div class="footer">
                    <p><strong>⚠️ Cet email a été envoyé automatiquement, merci de ne pas y répondre directement.</strong></p>
                    <p>Pour toute question, utilisez l'adresse : startuplab@contact.sn</p>
                    <p>Startup Lab - Programme d'accompagnement | Phase d'idéation et prototypage</p>
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
                'program': candidate_data.get('program', 'Startup Lab'),
                'submissionDate': candidate_data.get('created_at', '').strftime('%d/%m/%Y à %H:%M') if candidate_data.get('created_at') else '',
            }
        
            html_body = render_template_string(html_template, **template_data)
        
            # Créer et envoyer le message avec en-têtes pour empêcher les réponses
            msg = Message(
                subject=subject,
                recipients=[recipient],
                html=html_body,
                sender=default_sender,
                reply_to="noreply@startuplab.sn"
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
        """Envoyer une notification à l'admin pour Startup Lab"""
        try:
            subject = f"🚀 Nouvelle candidature Startup Lab - {candidate_data.get('companyName', 'N/A')}"
        
            # Obtenir l'email admin et l'expéditeur par défaut avec des valeurs de fallback
            admin_email = current_app.config.get('ADMIN_EMAIL')
            default_sender = current_app.config.get('MAIL_DEFAULT_SENDER', 'noreply@startuplab.sn')
        
            # Si pas d'email admin configuré, utiliser l'expéditeur par défaut
            recipient = admin_email if admin_email else default_sender
        
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
                .program-badge { background-color: #28a745; color: white; padding: 3px 8px; border-radius: 10px; font-size: 11px; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h2>🚀 Nouvelle candidature Startup Lab</h2>
                    <span class="program-badge">STARTUP LAB</span>
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
                        <span class="label">📋 Programme :</span> {{ program }}
                    </div>
                    <div class="info-row">
                        <span class="label">📅 Date :</span> {{ submissionDate }}
                    </div>
                    
                    <p style="margin-top: 20px; padding: 15px; background-color: #e8f4fd; border-radius: 5px;">
                        <strong>Action requise :</strong> Connectez-vous à l'interface d'administration pour examiner cette candidature Startup Lab en détail.
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
                'program': candidate_data.get('program', 'Startup Lab'),
                'submissionDate': candidate_data.get('created_at', '').strftime('%d/%m/%Y à %H:%M') if candidate_data.get('created_at') else '',
            }
        
            html_body = render_template_string(html_template, **template_data)
        
            msg = Message(
                subject=subject,
                recipients=[recipient],
                html=html_body,
                sender=default_sender
            )
        
            self.mail.send(msg)
            return True
        
        except Exception as e:
            print(f"Erreur lors de l'envoi de la notification admin: {e}")
            return False
