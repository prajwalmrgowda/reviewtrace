import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from test_project import fixture,ROOT
from google_docs import document_id,append_entry,check_document,authorized_session,check_response
from workflow import payload_digest,call_mcp_tools

DOC='example_document_1234567890'


class GoogleDocsTests(unittest.TestCase):
    def test_google_403_reason_is_visible_without_raw_error(self):
        for reason,expected in [('SERVICE_DISABLED','disabled'),('ACCESS_TOKEN_SCOPE_INSUFFICIENT','insufficient'),('forbidden','access denied')]:
            response=Mock(status_code=403)
            response.json.return_value={'error':{'message':'PRIVATE_RAW_ERROR','details':[{'reason':reason}]}}
            with self.subTest(reason=reason),self.assertRaises(RuntimeError) as failure:
                check_response(response)
            self.assertIn(expected,str(failure.exception))
            self.assertIn(reason,str(failure.exception))
            self.assertNotIn('PRIVATE_RAW_ERROR',str(failure.exception))

    def test_document_url_and_id(self):
        self.assertEqual(document_id(DOC),DOC)
        self.assertEqual(document_id(f'https://docs.google.com/document/d/{DOC}/edit?tab=t.0'),DOC)
        for value in ['', 'bad', 'https://evil.com/document/d/'+DOC, '../'+DOC]:
            with self.subTest(value=value), self.assertRaises(ValueError):document_id(value)
    def test_destination_changes_invalidate_approval(self):
        *_,entry,subject,body=fixture()
        local=payload_digest(entry,subject,body)
        remote=payload_digest(entry,subject,body,notes_destination='google_docs',document_id=DOC)
        self.assertNotEqual(local,remote)
        self.assertNotEqual(remote,payload_digest(entry,subject,body,notes_destination='google_docs',document_id=DOC+'2'))
        with self.assertRaises(PermissionError):
            asyncio.run(call_mcp_tools(entry,subject,body,approved=True,approved_digest=local,
                                      notes_destination='google_docs',document_id=DOC))
    def test_append_uses_official_batch_update(self):
        *_,entry,subject,body=fixture()
        session=Mock()
        session.post.return_value.status_code=200
        session.post.return_value.json.return_value={'documentId':DOC,'replies':[{}]}
        with patch('google_docs.authorized_session') as auth:
            auth.return_value.__enter__.return_value=session
            result=append_entry(DOC,entry)
        self.assertEqual(result['destination'],'Google Docs')
        args,kwargs=session.post.call_args
        self.assertEqual(args[0],f'https://docs.googleapis.com/v1/documents/{DOC}:batchUpdate')
        insertion=kwargs['json']['requests'][0]['insertText']
        self.assertEqual(insertion['endOfSegmentLocation'],{})
        self.assertIn(json.dumps(entry,indent=2,ensure_ascii=False),insertion['text'])
        self.assertEqual(kwargs['timeout'],15)
        session.post.assert_called_once()
    def test_connection_check_is_read_only(self):
        session=Mock()
        session.get.return_value.status_code=200
        session.get.return_value.json.return_value={'documentId':DOC,'title':'Product notes'}
        with patch('google_docs.authorized_session') as auth:
            auth.return_value.__enter__.return_value=session
            self.assertEqual(check_document(DOC)['title'],'Product notes')
        session.post.assert_not_called()
    def test_errors_are_actionable_and_do_not_retry_append(self):
        *_,entry,subject,body=fixture()
        for status in [401,403,404,429,500]:
            session=Mock()
            session.post.return_value.status_code=status
            with self.subTest(status=status),patch('google_docs.authorized_session') as auth:
                auth.return_value.__enter__.return_value=session
                with self.assertRaises(RuntimeError):append_entry(DOC,entry)
                session.post.assert_called_once()
    def test_network_failure_does_not_leak_credentials_or_replay(self):
        *_,entry,subject,body=fixture()
        session=Mock()
        session.post.side_effect=RuntimeError('network failed')
        with patch('google_docs.authorized_session') as auth:
            auth.return_value.__enter__.return_value=session
            with self.assertRaises(RuntimeError):append_entry(DOC,entry)
        session.post.assert_called_once()
    def test_missing_credentials_fail_clearly(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaisesRegex(ValueError,'credentials'):authorized_session()
    def test_mcp_remote_route_requires_gate_and_produces_receipt(self):
        from mcp_server import append_product_notes
        *_,entry,subject,body=fixture()
        digest=payload_digest(entry,subject,body,notes_destination='google_docs',document_id=DOC)
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{
            'REVIEWPULSE_APPROVAL_TOKEN':'token','REVIEWPULSE_APPROVED_DIGEST':digest,
            'REVIEWPULSE_NOTES_DESTINATION':'google_docs','REVIEWPULSE_GOOGLE_DOC_ID':DOC,
            'REVIEWPULSE_OUTPUT_DIR':d}),patch('google_docs.append_entry') as append:
            append.return_value={'destination':'Google Docs','document_id':DOC,'url':'https://docs.google.com/document/d/'+DOC+'/edit','status':'appended'}
            with self.assertRaises(PermissionError):append_product_notes(json.dumps(entry),subject,body,'bad')
            append.assert_not_called()
            result=json.loads(append_product_notes(json.dumps(entry),subject,body,'token'))
            append.assert_called_once_with(DOC,entry)
            self.assertEqual(json.loads(Path(result['path']).read_text())['status'],'appended')
            self.assertFalse((Path(d)/'internal_product_notes.md').exists())
    def test_real_mcp_google_mode_fails_without_credentials_and_never_falls_back(self):
        *_,entry,subject,body=fixture()
        digest=payload_digest(entry,subject,body,notes_destination='google_docs',document_id=DOC)
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{
            'GOOGLE_APPLICATION_CREDENTIALS':'', 'REVIEWPULSE_GOOGLE_CREDENTIALS_JSON':''}):
            with self.assertRaises(Exception):
                asyncio.run(call_mcp_tools(entry,subject,body,approved=True,approved_digest=digest,
                    output_dir=d,notes_destination='google_docs',document_id=DOC))
            self.assertEqual(list(Path(d).iterdir()),[])

    def test_verified_connection_persists_and_new_doc_requires_check_and_approval(self):
        from streamlit.testing.v1 import AppTest
        metadata={'document_id':DOC,'title':'Product notes','url':f'https://docs.google.com/document/d/{DOC}/edit'}
        with patch.dict(os.environ,{'GOOGLE_APPLICATION_CREDENTIALS':'/tmp/test-only-credentials.json'}),patch('google_docs.check_document',return_value=metadata) as check:
            app=AppTest.from_file(str(ROOT/'app.py')).run()
            app.radio[0].set_value('Google Docs').run()
            next(item for item in app.text_input if item.label=='Google Doc URL or ID').set_value(DOC).run()
            next(button for button in app.button if button.label=='Check Google Docs connection').click().run()
            check.assert_called_once()
            self.assertTrue(any('Connected: Product notes' in message.value for message in app.success))
            app.checkbox[0].check().run()
            self.assertTrue(any('Connected: Product notes' in message.value for message in app.success))
            self.assertFalse(next(button for button in app.button if button.label=='Append notes & create draft').disabled)
            next(item for item in app.text_input if item.label=='Google Doc URL or ID').set_value(DOC+'2').run()
            self.assertFalse(app.checkbox[0].value)
            self.assertTrue(next(button for button in app.button if button.label=='Append notes & create draft').disabled)
            self.assertFalse(app.exception)

    def test_docs_setup_does_not_crash_ui_or_enable_writes(self):
        from streamlit.testing.v1 import AppTest
        with patch.dict(os.environ,{},clear=True):
            app=AppTest.from_file(str(ROOT/'app.py')).run()
            app.radio[0].set_value('Google Docs').run()
            self.assertFalse(app.exception)
            self.assertTrue(next(b for b in app.button if b.label=='Check Google Docs connection').disabled)
            app.checkbox[0].check().run()
            self.assertTrue(next(b for b in app.button if b.label=='Append notes & create draft').disabled)

if __name__=='__main__':unittest.main()
