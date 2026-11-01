"""HTTP security regressions; only synthetic files and mocked user records."""
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from flask import Flask
import jwt
import zipfile
from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import Unauthorized, ServiceUnavailable

from app.models.user import FileField, StudentProfile
from app.routes.auth_routes import auth_bp
from app.routes.admin_routes import admin_bp
from app.routes.candidature_routes import candidature_bp, candidature_public_bp
from app.routes.candidature_startup_routes import startup_bp
from app.routes.resource_request_routes import resource_bp
from app.routes.test_routes import test_bp
from app.routes.competence_routes import competence_bp
from app.routes.startup_school_routes import startup_school_bp
from app.routes.job_offer_routes import job_offer_bp
from app.services.auth_service import AuthService
from app.services.profiles.profile_service import ProfileService, ProfileValidationError
from app.utils.application_security import install_application_security
from app.utils.error_handlers import register_error_handlers
from app.utils.request_guards import RATE_LIMIT_LOCK, RATE_LIMIT_STORE
from app.utils.upload_security import validate_upload, DOCUMENT_EXTENSIONS
from app.services.events.event_service import EventService
from app.services.oauth_service import GoogleOAuthService, LinkedInOAuthService


class ApplicationSecurityTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.app=Flask(__name__,static_folder=str(self.root/'static'),static_url_path='/static')
        self.app.config.update(TESTING=True,JWT_SECRET_KEY='isolated-security-key-'+'a'*32,UPLOAD_FOLDER=str(self.root/'uploads'),FRONTEND_URL='https://frontend.example.test')
        for blueprint,prefix in ((auth_bp,'/api/auth'),(admin_bp,'/api/admin'),(candidature_bp,'/api/admin'),(candidature_public_bp,'/api/candidature'),(test_bp,'/api/admin'),(startup_bp,'/api/startup'),(resource_bp,'/api/resources'),(competence_bp,'/api/competences'),(startup_school_bp,'/api/startup-school'),(job_offer_bp,'/api/job-offers')):
            self.app.register_blueprint(blueprint,url_prefix=prefix)
        install_application_security(self.app)
        register_error_handlers(self.app)
        self.client=self.app.test_client()
        self.client.environ_base['REMOTE_ADDR']='127.44.0.1'
        with RATE_LIMIT_LOCK:
            RATE_LIMIT_STORE.clear()
        self.users={}
        for identity,admin_type,scope,active in (
            ('owner',None,None,True),('other',None,None,True),
            ('admin','super_admin',None,True),('jury','competences','interview_member',True),
            ('startup','startups',None,True),('inactive','super_admin',None,False),
        ):
            self.users[identity]=SimpleNamespace(id=identity,is_admin=bool(admin_type),admin_type=admin_type,
                profile_data={'admin_scope':scope},is_active=active,profile_type='student',
                student_profile=StudentProfile(institution='Test',education_level='Test',sector='Test',
                    cv_file=FileField(filename=identity+'.pdf',path=f'students/cv/{identity}.pdf')))
        model=self.enterContext(patch('app.services.auth_service.User'))
        model.objects.side_effect=lambda **kwargs: SimpleNamespace(first=lambda:self.users.get(kwargs.get('id')))
        self.model=model
        self.requests=self.enterContext(patch('app.routes.resource_request_routes.resource_request_service.list_all',return_value=[{'synthetic':True}]))

    def headers(self,identity='owner',**overrides):
        now=datetime.now(timezone.utc)
        payload={'sub':identity,'user_id':identity,'iat':now,'exp':now+timedelta(minutes=5),'is_admin':True,'admin_type':'super_admin',**overrides}
        token=jwt.encode(payload,self.app.config['JWT_SECRET_KEY'],algorithm='HS256')
        return {'Authorization':'Bearer '+token}

    def test_anonymous_private_endpoints_reject_before_data_access(self):
        paths=('/api/resources/all','/api/startup/list','/api/startup/uploads/private.pdf',
               '/api/admin/candidatures','/api/admin/tests','/api/admin/tests/results',
               '/api/admin/tests/results/export','/api/admin/admin-profiles','/api/admin/interview-members')
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code,401)
        self.requests.assert_not_called()
        self.model.objects.assert_not_called()

    def test_db_roles_override_forged_or_stale_jwt_role_claims(self):
        for identity in ('owner','jury','inactive'):
            with self.subTest(identity=identity):
                response=self.client.get('/api/resources/all',headers=self.headers(identity))
                self.assertIn(response.status_code,(401,403))
        self.requests.assert_not_called()
        self.assertEqual(self.client.get('/api/resources/all',headers=self.headers('admin')).status_code,200)
        self.requests.assert_called_once_with()

    def test_invalid_expired_and_incomplete_tokens_fail_closed(self):
        responses=[self.client.get('/api/resources/all',headers={'Authorization':'Bearer invalid'})]
        responses.append(self.client.get('/api/resources/all',headers=self.headers(exp=datetime.now(timezone.utc)-timedelta(minutes=1))))
        incomplete=jwt.encode({'sub':'admin','iat':datetime.now(timezone.utc),'exp':datetime.now(timezone.utc)+timedelta(minutes=1)},self.app.config['JWT_SECRET_KEY'],algorithm='HS256')
        responses.append(self.client.get('/api/resources/all',headers={'Authorization':'Bearer '+incomplete}))
        self.assertTrue(all(response.status_code==401 for response in responses))
        self.requests.assert_not_called()
        self.model.objects.assert_not_called()

    def test_document_owner_allowed_other_user_denied_and_not_cached(self):
        path=self.root/'uploads'/'students'/'cv'/'owner.pdf'
        path.parent.mkdir(parents=True)
        path.write_bytes(b'%PDF-1.7\nSynthetic private content')
        endpoint='/api/auth/documents/students/cv/owner.pdf'
        self.assertEqual(self.client.get(endpoint).status_code,401)
        denied=self.client.get(endpoint,headers=self.headers('other'))
        self.assertEqual(denied.status_code,404)
        self.assertNotIn(b'Synthetic private content',denied.data)
        response=self.client.get(endpoint,headers=self.headers())
        self.assertEqual(response.status_code,200)
        self.assertIn('attachment',response.headers['Content-Disposition'])
        self.assertEqual(response.headers['Cache-Control'],'private, no-store')
        response.close()

    def test_private_static_documents_blocked_but_public_event_image_kept(self):
        folder=self.root/'static'/'uploads'/'students'/'cv'
        folder.mkdir(parents=True)
        (folder/'known.pdf').write_bytes(b'private')
        (self.root/'static'/'uploads'/'event.png').write_bytes(b'image')
        response=self.client.get('/static/uploads/students/cv/known.pdf')
        self.assertEqual(response.status_code,404)
        self.assertNotIn(b'private',response.data)
        image=self.client.get('/static/uploads/event.png')
        self.assertEqual(image.status_code,200)
        image.close()

    def test_login_rate_limit_shared_between_admin_and_user_routes(self):
        with patch.object(AuthService,'login_with_email',side_effect=Unauthorized('Invalid')), patch.object(AuthService,'login_admin',side_effect=Unauthorized('Invalid')):
            for index in range(10):
                path='/api/auth/login' if index%2 else '/api/admin/login'
                self.assertEqual(self.client.post(path,json={'email':'test@example.org','password':'invalid'}).status_code,401)
            self.assertEqual(self.client.post('/api/auth/login',json={'email':'test@example.org','password':'invalid'}).status_code,429)

    def test_login_rejects_query_objects_and_oversize_body_before_auth(self):
        with patch.object(AuthService,'login_with_email') as login:
            response=self.client.post('/api/auth/login',json={'email':{'$ne':None},'password':'invalid'})
            self.assertEqual(response.status_code,400)
            oversized=self.client.post('/api/auth/login',json={'email':'test@example.org','password':'a'*70000})
            self.assertEqual(oversized.status_code,413)
            login.assert_not_called()

    def test_inactive_oauth_account_and_unverified_account_link_are_rejected(self):
        with self.app.app_context():
            self.model.objects.side_effect=None
            self.model.objects.return_value.first.return_value=self.users['inactive']
            with self.assertRaises(Unauthorized):
                AuthService.login_with_oauth('google','provider-id',{'email':'x@example.org','email_verified':True})
            self.model.objects.return_value.first.return_value=None
            with self.assertRaises(Unauthorized):
                AuthService.login_with_oauth('google','provider-id',{'email':'x@example.org','email_verified':False})

    def test_disguised_executable_rejected_and_file_size_checked(self):
        fake=FileStorage(stream=BytesIO(b'MZ executable'),filename='cv.pdf',content_type='application/pdf')
        with self.assertRaises(ValueError):
            validate_upload(fake,DOCUMENT_EXTENSIONS,1024)
        pdf=FileStorage(stream=BytesIO(b'%PDF-1.7\n'+b'a'*200),filename='cv.pdf')
        with self.assertRaises(ValueError):
            validate_upload(pdf,DOCUMENT_EXTENSIONS,100)
        self.assertGreater(validate_upload(pdf,DOCUMENT_EXTENSIONS,1024),0)

    def test_profile_rejects_active_content_without_writing_files(self):
        svg=FileStorage(stream=BytesIO(b'<svg onload="alert(1)"/>'),filename='logo.svg')
        with self.assertRaises(ProfileValidationError):
            ProfileService._save_file(svg,str(self.root),'startups/logos')
        self.assertFalse((self.root/'startups').exists())

    def test_event_upload_cannot_write_outside_upload_directory_or_overwrite(self):
        folder=str(self.root/'static')
        first=FileStorage(stream=BytesIO(b'\x89PNG\r\n\x1a\nfixture'),filename='../../escaped.png')
        second=FileStorage(stream=BytesIO(b'\x89PNG\r\n\x1a\nfixture'),filename='../../escaped.png')
        a=EventService._save_image(first,folder)
        b=EventService._save_image(second,folder)
        self.assertNotEqual(a,b)
        self.assertFalse((self.root/'escaped.png').exists())
        self.assertEqual(len(list((self.root/'static'/'uploads').iterdir())),2)

    def test_startup_documents_require_the_correct_administrative_role(self):
        folder=self.root/'startup-files'
        folder.mkdir()
        (folder/'cv.pdf').write_bytes(b'%PDF-1.7\nSynthetic')
        with patch('app.routes.candidature_startup_routes.UPLOAD_FOLDER',str(folder)):
            self.assertEqual(self.client.get('/api/startup/uploads/cv.pdf',headers=self.headers()).status_code,401)
            response=self.client.get('/api/startup/uploads/cv.pdf',headers=self.headers('startup'))
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.headers['Cache-Control'],'private, no-store')
            response.close()

    def test_oauth_redirect_does_not_put_session_token_in_query_string(self):
        with patch('app.routes.auth_routes.GoogleOAuthService.validate_state'), patch('app.routes.auth_routes.GoogleOAuthService.get_token',return_value={'access_token':'provider-token'}), patch('app.routes.auth_routes.GoogleOAuthService.get_user_info',return_value={'oauth_id':'fixture'}), patch.object(AuthService,'login_with_oauth',return_value={'token':'synthetic-session'}):
            response=self.client.get('/api/auth/google/callback?code=fixture')
        self.assertEqual(response.status_code,302)
        self.assertEqual(response.headers['Location'],'https://frontend.example.test/oauth-callback#token=synthetic-session')
        self.assertEqual(response.headers['Cache-Control'],'no-store')

    def test_registration_payload_cannot_grant_administrative_roles(self):
        from test_profile_service import FakeUserRepository
        user=ProfileService(FakeUserRepository()).register({
            'email':'synthetic@example.com','password':'Test-secret-123','profileType':'student',
            'is_admin':True,'admin_type':'super_admin','profile_data':{'admin_scope':'super_admin'},
        },{},str(self.root))
        self.assertFalse(getattr(user,'is_admin',False))
        self.assertIsNone(getattr(user,'admin_type',None))
        self.assertNotIn('admin_scope',user.profile_data)

    def test_office_container_rejects_macros_and_excessive_expansion(self):
        for entries in (
            {'[Content_Types].xml':b'x','word/document.xml':b'x','word/vbaProject.bin':b'macro'},
            {'[Content_Types].xml':b'x','word/document.xml':b'a'*100000},
        ):
            with self.subTest(entries=list(entries)):
                stream=BytesIO()
                with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED) as archive:
                    for name,data in entries.items():
                        archive.writestr(name,data)
                stream.seek(0)
                with self.assertRaises(ValueError):
                    validate_upload(FileStorage(stream=stream,filename='test.docx'),DOCUMENT_EXTENSIONS,4096)

    def test_catalog_writes_reject_regular_and_jury_users_before_persistence(self):
        for path,module,attribute in (
            ('/api/competences/','app.routes.competence_routes','competence_service'),
            ('/api/startup-school/','app.routes.startup_school_routes','startup_school_service'),
            ('/api/job-offers/','app.routes.job_offer_routes','job_offer_service'),
        ):
            with self.subTest(path=path), patch(module+'.'+attribute+'.create',return_value=SimpleNamespace(to_dict=lambda:{'synthetic':True})) as create:
                for identity in ('owner','jury'):
                    self.assertIn(self.client.post(path,json={},headers=self.headers(identity)).status_code,(401,403))
                create.assert_not_called()
                self.assertEqual(self.client.post(path,json={},headers=self.headers('admin')).status_code,201)
                create.assert_called_once_with({})

    def test_production_oauth_refuses_http_callbacks_before_provider_redirect(self):
        self.app.config['ENVIRONMENT']='production'
        with self.app.app_context():
            for service in (GoogleOAuthService,LinkedInOAuthService):
                with self.subTest(provider=service.__name__), self.assertRaises(ServiceUnavailable):
                    service.get_auth_url('http://legacy.example.test:5000/callback')
