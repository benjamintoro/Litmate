"""Contrato de producción, apertura segura y operación en datos sintéticos."""
import base64
from contextlib import closing
from dataclasses import replace
from io import BytesIO
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.conf import settings
from django.contrib.auth.models import User
from django.db import connections
from django.test import Client,TestCase,SimpleTestCase,RequestFactory,override_settings
from litmate_project.production_config import ProductionConfig
from core.production_gateway import ProductionGateway


class ConfigGatewayTests(SimpleTestCase):
    def config(self,**changes):
        env={'LITMATE_PUBLIC_ORIGIN':'https://litmate.example.test','LITMATE_PROXY_MODE':'loopback-tls',
            'LITMATE_ACCOUNTS_DB':str(Path(settings.BASE_DIR)/'.testtmp/config/accounts/users.sqlite3'),
            'LITMATE_PRODUCTION_RUNTIME':str(Path(settings.BASE_DIR)/'.testtmp/config/runtime'),
            'LITMATE_PRODUCTION_TESTING':'1',**changes}
        return ProductionConfig.from_environment(settings.BASE_DIR,env)

    def call(self,config=None,**environ):
        captured={}
        def app(env,start):
            captured.update(env);start('200 OK',[]);return [b'ok']
        gate=ProductionGateway(app,config or self.config(),password='Synthetic-Private-Gateway-Key-64!')
        env=RequestFactory().get('/chat/',HTTP_HOST='litmate.example.test').environ
        env.update(environ);status=[]
        body=b''.join(gate(env,lambda line,headers:status.append((line,headers))))
        return status[0],captured,body

    def test_origin_is_configurable_and_never_assumes_a_tailscale_domain(self):
        self.assertEqual(self.config(LITMATE_PUBLIC_ORIGIN='https://books.example.org').host,'books.example.org')
        self.assertEqual(self.config(LITMATE_PUBLIC_ORIGIN='https://books.example.org:4443/').origin,'https://books.example.org:4443')

    def test_origins_with_credentials_paths_wildcards_or_http_are_rejected(self):
        for origin in ['http://books.example.org','https://u:p@books.example.org','https://*.example.org',
                       'https://books.example.org/path','https://books.example.org/?key=x','https://books.example.org/#x']:
            with self.subTest(origin=origin),self.assertRaises(ValueError):self.config(LITMATE_PUBLIC_ORIGIN=origin)

    def test_explicit_proxy_and_isolated_storage_are_required(self):
        for change in [{'LITMATE_PROXY_MODE':''},{'LITMATE_ACCOUNTS_DB':str(Path(settings.BASE_DIR)/'data/accounts/users.sqlite3')},
                       {'LITMATE_ACCESS_GATE':'unexpected'}]:
            with self.assertRaises(ValueError):self.config(**change)

    def test_open_gate_has_no_basic_challenge_and_ignores_forwarded_headers(self):
        status,env,_=self.call(HTTP_X_FORWARDED_HOST='evil.example.org',HTTP_X_FORWARDED_PROTO='http',HTTP_X_FORWARDED_FOR='10.1.1.1')
        self.assertEqual(status[0],'200 OK')
        self.assertNotIn('HTTP_X_FORWARDED_HOST',env)
        self.assertEqual(env['wsgi.url_scheme'],'https')
        self.assertFalse(any(key=='WWW-Authenticate' for key,value in status[1]))

    def test_remote_proxy_host_and_private_paths_are_rejected(self):
        self.assertTrue(self.call(REMOTE_ADDR='10.0.0.1')[0][0].startswith('403'))
        self.assertTrue(self.call(HTTP_HOST='evil.example.org')[0][0].startswith('400'))
        self.assertTrue(self.call(HTTP_HOST='litmate.example.test:666')[0][0].startswith('400'))
        for path in ['/admin/','/.env','/data/accounts/users.sqlite3','/backups/','/static/../data/x']:
            self.assertTrue(self.call(PATH_INFO=path)[0][0].startswith('404'),path)

    def test_basic_remains_explicit_optional_and_credentials_are_not_forwarded(self):
        config=self.config(LITMATE_ACCESS_GATE='basic')
        self.assertTrue(self.call(config)[0][0].startswith('401'))
        encoded=base64.b64encode(b'demo:Synthetic-Private-Gateway-Key-64!').decode()
        status,env,_=self.call(config,HTTP_AUTHORIZATION='Basic '+encoded)
        self.assertEqual(status[0],'200 OK');self.assertNotIn('HTTP_AUTHORIZATION',env)

    def test_runtime_cannot_adopt_an_unmarked_directory(self):
        from .production_runtime import prepare_runtime
        with TemporaryDirectory(dir=Path(settings.BASE_DIR)/'.testtmp') as temporary:
            with self.assertRaises(ValueError):prepare_runtime(replace(self.config(),runtime=Path(temporary)))

    def test_instance_lease_is_exclusive_and_port_check_refuses_occupied_socket(self):
        import socket
        from .production_runtime import FileLease,ensure_port_free
        with TemporaryDirectory(dir=Path(settings.BASE_DIR)/'.testtmp') as temporary:
            with FileLease(Path(temporary)/'operation.lock'):
                with self.assertRaises(ValueError):
                    with FileLease(Path(temporary)/'operation.lock'):pass
        with socket.socket() as sock:
            sock.bind(('127.0.0.1',0));sock.listen()
            with self.assertRaises(OSError):ensure_port_free(sock.getsockname()[1])

    def synthetic_backup_source(self,folder):
        path=Path(folder)/'source/accounts.sqlite3';path.parent.mkdir()
        with closing(sqlite3.connect(path)) as db,db:
            for table in ['auth_user','django_session','reader_accounts_usagebucket','reader_accounts_queryoperation']:
                db.execute('CREATE TABLE '+table+'(id INTEGER PRIMARY KEY)')
            db.execute('CREATE TABLE core_perfilusuario(id INTEGER PRIMARY KEY,imagen TEXT)')
            db.execute('INSERT INTO auth_user VALUES(1)')
        from .signing_key import load_key
        load_key(path)
        return path

    def test_supervisor_retries_are_bounded(self):
        from scripts.production.supervise import delays
        self.assertEqual(delays(3),[0,5,15,60])
        self.assertEqual(delays(0),[0])
        with self.assertRaises(ValueError):delays(4)

    def test_testing_cannot_use_the_public_listener_port(self):
        with self.assertRaises(ValueError):self.config(LITMATE_PRODUCTION_PORT='8003')

    def test_supervisor_recovers_a_failed_synthetic_process_then_stops(self):
        import sys
        from scripts.production.supervise import run_supervised
        with TemporaryDirectory(dir=Path(settings.BASE_DIR)/'.testtmp') as temporary:
            folder=Path(temporary);marker=folder/'child-attempts'
            script='from pathlib import Path;import sys;p=Path(sys.argv[1]);n=int(p.read_text())+1 if p.exists() else 1;p.write_text(str(n));sys.exit(1 if n==1 else 0)'
            self.assertEqual(run_supervised([sys.executable,'-B','-c',script,str(marker)],folder,[0,0]),0)
            self.assertEqual(marker.read_text(),'2')
            state=json.loads((folder/'supervisor.json').read_text())
            self.assertEqual((state['attempt'],state['exit_code']),(2,0))

    def test_supervisor_obeys_stop_without_starting_any_process(self):
        from scripts.production.supervise import run_supervised
        with TemporaryDirectory(dir=Path(settings.BASE_DIR)/'.testtmp') as temporary:
            folder=Path(temporary);(folder/'stop.request').touch()
            with patch('scripts.production.supervise.subprocess.Popen') as popen:
                self.assertEqual(run_supervised(['not-executed'],folder,[0]),0)
                popen.assert_not_called()

    def test_release_patch_handles_missing_final_newline_in_both_directions(self):
        import os,subprocess
        from scripts.accounts.package_release import delta
        with TemporaryDirectory(dir=Path(settings.BASE_DIR)/'.testtmp') as temporary:
            folder=Path(temporary);target=folder/'sample.html';patch_file=folder/'change.patch'
            before=b'first\nlast';after=b'first\nmodified\n'
            patch_file.write_text(delta('sample.html',before,after,existed=True),encoding='utf8',newline='\n')
            environment={**os.environ,'GIT_CEILING_DIRECTORIES':str(folder.parent)}
            target.write_bytes(before)
            forward=subprocess.run(['git','apply','--check','--no-index',str(patch_file)],cwd=folder,env=environment,capture_output=True)
            self.assertEqual(forward.returncode,0,forward.stderr)
            target.write_bytes(after)
            reverse=subprocess.run(['git','apply','--reverse','--check','--no-index',str(patch_file)],cwd=folder,env=environment,capture_output=True)
            self.assertEqual(reverse.returncode,0,reverse.stderr)

    def test_release_creation_and_verification_share_the_same_root_allowlist(self):
        from scripts.accounts.package_release import allowed_file
        for name in ['iniciar_produccion.py','requirements-production.txt','scripts/production/PrepararTareas.ps1']:
            self.assertTrue(allowed_file(name),name)
        for name in ['.env','users.sqlite3','data/accounts/users.sqlite3','core/../../.env','arbitrary.py']:
            self.assertFalse(allowed_file(name),name)

    def test_backup_job_restores_skips_recent_and_never_deletes_retention_candidates(self):
        from scripts.accounts.backup_job import run_backup
        with TemporaryDirectory(dir=Path(settings.BASE_DIR)/'.testtmp') as temporary:
            source=self.synthetic_backup_source(temporary);destination=Path(temporary)/'backups'
            first=run_backup(source,destination,keep=2,interval_hours=0)
            self.assertTrue(first['restore_verified'])
            self.assertEqual(run_backup(source,destination)['status'],'recent_backup_valid')
            run_backup(source,destination,keep=2,interval_hours=0)
            third=run_backup(source,destination,keep=2,interval_hours=0)
            self.assertEqual(len(third['retention_candidates']),1)
            self.assertEqual(len(list(destination.glob('backup-*'))),4)  # Tres directorios más marcador.
            self.assertTrue((destination/first['backup']).is_dir())

    def test_backup_job_pause_and_exclusive_worker(self):
        from scripts.accounts.backup_job import run_backup
        from .production_runtime import FileLease
        with TemporaryDirectory(dir=Path(settings.BASE_DIR)/'.testtmp') as temporary:
            source=self.synthetic_backup_source(temporary);destination=Path(temporary)/'backups'
            run_backup(source,destination)
            (destination/'pause.request').touch()
            self.assertEqual(run_backup(source,destination)['status'],'paused')
            with FileLease(destination/'job.lock'):
                with self.assertRaises(ValueError):run_backup(source,destination)

    def test_backup_job_detects_corruption_without_touching_source(self):
        from scripts.accounts.backup_job import run_backup
        with TemporaryDirectory(dir=Path(settings.BASE_DIR)/'.testtmp') as temporary:
            source=self.synthetic_backup_source(temporary);destination=Path(temporary)/'backups'
            result=run_backup(source,destination)
            (destination/result['backup']/'accounts.sqlite3').write_bytes(b'CORRUPT SYNTHETIC BACKUP')
            before=source.read_bytes()
            with self.assertRaises(ValueError):run_backup(source,destination)
            self.assertEqual(before,source.read_bytes())


class OpenProductionTests(TestCase):
    databases={'accounts'}

    def setUp(self):
        temporary=self.enterContext(TemporaryDirectory(dir=Path(settings.BASE_DIR)/'.testtmp'))
        self.enterContext(override_settings(LITMATE_AI_RUNTIME_DB=Path(temporary)/'runtime.sqlite3'))
        self.client.defaults['HTTP_HOST']=settings.PRODUCTION.host

    def get(self,path,**kwargs):return self.client.get(path,secure=True,**kwargs)
    def post(self,path,data,**kwargs):return self.client.post(path,data,secure=True,**kwargs)
    def register(self,username='open-reader',email='open@example.invalid'):
        self.get('/registro/')
        return self.post('/registro/',{'username':username,'email':email,'password':'Alamo-64-Prueba-Segura!',
            'password_confirm':'Alamo-64-Prueba-Segura!'})

    def test_registration_without_basic_selects_free_and_preserves_account(self):
        from suscripciones.models import PlanSuscripcion,SuscripcionUsuario
        PlanSuscripcion.objects.create(nombre='Gratuito',slug='gratis',precio=0,limite_consultas_ia_diarias=15)
        self.assertEqual(self.get('/registro/').status_code,200)
        self.assertEqual(self.register().status_code,302)
        self.assertEqual(self.post('/cuenta/activar-gratis/',{'plan':'gratis'}).status_code,302)
        self.assertEqual(SuscripcionUsuario.objects.get().plan.slug,'gratis')
        self.assertContains(self.get('/perfil/'),'15 disponibles')

    @override_settings(LITMATE_SIGNUP_GLOBAL_PER_HOUR=1)
    def test_cookie_rotation_cannot_bypass_the_global_creation_budget(self):
        self.assertEqual(self.register().status_code,302)
        self.client.logout()
        self.client.cookies.clear()
        result=self.register('second-reader','second@example.invalid')
        self.assertContains(result,'límite temporal',status_code=429)
        self.assertEqual(User.objects.count(),1)

    def test_registration_without_established_visitor_is_not_created(self):
        result=self.post('/registro/',{'username':'direct','email':'direct@example.invalid',
            'password':'Alamo-64-Prueba-Segura!','password_confirm':'Alamo-64-Prueba-Segura!'})
        self.assertEqual(result.status_code,429)
        self.assertEqual(User.objects.count(),0)

    def test_open_registration_and_login_do_not_offer_unconfigured_oauth_or_analytics(self):
        for route in ['/login/','/registro/']:
            page=self.get(route)
            self.assertNotContains(page,'googletagmanager.com')
            self.assertNotContains(page,'class="btn btn-social')
            self.assertNotContains(page,'contraseña privada de la demo')

    def test_csrf_is_required_and_other_users_history_is_not_accessible(self):
        from core.models import ConversacionIA
        owner=User.objects.create_user('own');other=User.objects.create_user('other')
        conv=ConversacionIA.objects.create(usuario=other,titulo='PRIVATE HISTORY')
        self.client.force_login(owner)
        self.assertEqual(self.get(f'/cuenta/conversaciones/{conv.pk}/').status_code,404)
        client=Client(enforce_csrf_checks=True,HTTP_HOST=settings.PRODUCTION.host)
        self.assertEqual(client.post('/registro/',{},secure=True).status_code,403)

    def test_health_is_minimal_and_ready_detects_database_failure(self):
        self.assertEqual(self.get('/_health/live/').json(),{'status':'ok'})
        self.assertEqual(self.get('/_health/ready/').json(),{'status':'ok'})
        from django.db import DatabaseError
        with patch.object(connections['accounts'],'cursor',side_effect=DatabaseError('PRIVATE ERROR')):
            response=self.get('/_health/ready/')
        self.assertEqual(response.status_code,503)
        self.assertNotIn('PRIVATE ERROR',response.content.decode())

    def test_operations_admin_requires_staff_and_model_permission(self):
        owner=User.objects.create_user('reader')
        staff=User.objects.create_user('restricted',is_staff=True)
        operator=User.objects.create_superuser('operator','ops@example.invalid','Synthetic-64-Password!')
        self.client.force_login(owner)
        self.assertEqual(self.get('/operacion/').status_code,302)
        self.client.force_login(staff)
        self.assertEqual(self.get('/operacion/estado/').status_code,403)
        self.client.force_login(operator)
        page=self.get('/operacion/estado/')
        self.assertContains(page,'Estado operativo')
        self.assertNotContains(page,str(settings.SECRET_KEY))
        self.assertEqual(self.get('/operacion/core/mensajeia/').status_code,404)

    def test_operator_can_view_safe_metadata_but_cannot_edit_plans_or_users(self):
        from suscripciones.models import PlanSuscripcion
        operator=User.objects.create_superuser('readonly-operator','ops@example.invalid','Synthetic-64-Password!')
        plan=PlanSuscripcion.objects.create(nombre='Gratuito',slug='gratis',precio=0,limite_consultas_ia_diarias=15)
        self.client.force_login(operator)
        self.assertContains(self.get('/operacion/auth/user/'),'readonly-operator')
        page=self.get(f'/operacion/auth/user/{operator.pk}/change/')
        self.assertNotContains(page,operator.password)
        self.assertNotContains(page,'name="password"')
        self.assertEqual(self.post(f'/operacion/suscripciones/plansuscripcion/{plan.pk}/change/',{'precio':'999'}).status_code,403)
        plan.refresh_from_db();self.assertEqual(plan.precio,0)

    def test_private_favorite_suggestion_and_reading_list_never_become_thematic_recommendations(self):
        from .personal_chat import answer,intent
        from core.models import LibroFavorito
        owner=User.objects.create_user('personal');other=User.objects.create_user('unrelated')
        LibroFavorito.objects.create(usuario=owner,google_id='book-one',titulo='Obra propia',autores='Autora')
        LibroFavorito.objects.create(usuario=other,google_id='private',titulo='PRIVATE OTHER FAVORITE')
        response=answer('Recomiéndame uno de mis favoritos',owner)
        self.assertEqual(len(response['books']),1)
        self.assertEqual(response['books'][0]['title'],'Obra propia')
        self.assertEqual(intent('Muéstrame mi lista de lectura'),'reading_list')
        self.assertIsNone(intent('Recomiéndame fantasía sobre bibliotecas'))

    def test_production_runtime_and_domain_are_separate_from_demo(self):
        self.assertFalse(settings.DEBUG)
        self.assertEqual(settings.ROOT_URLCONF,'litmate_project.production_urls')
        self.assertTrue(settings.SESSION_COOKIE_SECURE and settings.CSRF_COOKIE_SECURE)
        self.assertEqual(settings.CSRF_TRUSTED_ORIGINS,[settings.LITMATE_PUBLIC_ORIGIN])
        self.assertNotIn('demo',str(settings.LITMATE_AI_STREAM_DB))

    def test_cached_audio_requires_the_generating_session(self):
        path='/media/tts_cache/miku_'+'a'*64+'.mp3'
        self.assertEqual(self.get(path).status_code,404)

    def test_preflight_reports_missing_model_and_optional_search_failure(self):
        from .production_runtime import preflight
        config=replace(settings.PRODUCTION,accounts=Path(connections['accounts'].settings_dict['NAME']))
        with patch('reader_accounts.production_runtime.local_json',side_effect=[{'models':[]},OSError()]):
            result=preflight(config)
        self.assertFalse(result['ready'])
        self.assertIn('ollama_model_missing',result['errors'])
        self.assertIn('searxng_unavailable_local_retrieval_remains',result['warnings'])
