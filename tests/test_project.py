import asyncio
import csv
from datetime import date
from email import policy
from email.parser import BytesParser
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from engine import load_csv, analyze, pulse, fee_explainer, validate_outputs, THEMES, EXPLANATION, OFFICIAL, FEE
from workflow import call_mcp_tools, payload_digest


def fixture():
    a=analyze(load_csv((ROOT/'reviews_sample.csv').read_bytes()),date(2026,10,20))
    weekly=pulse(a); explanation=fee_explainer(a)
    entry={'date':a['as_of'],'top_themes':[{'theme':n,'count':c} for n,c in a['top']],
           'weekly_pulse':weekly,'identified_fee_issue':FEE,'explanation_bullets':EXPLANATION,'source_links':OFFICIAL}
    subject='Weekly Product Pulse + Customer Clarification — ChatGPT Mobile'
    return a,weekly,explanation,entry,subject,weekly+'\n\nReusable support snippet\n'+explanation


class IntelligenceTests(unittest.TestCase):
    def test_assignment_outputs(self):
        a,w,e,*_=fixture()
        self.assertEqual(validate_outputs(a,w,e),[])
        self.assertLess(len(w.split()),250)
        self.assertLessEqual(len(a['themes']),5)
        self.assertEqual(len(a['top']),3)
        self.assertEqual(len(a['quotes']),3)
        self.assertEqual(len([l for l in e.splitlines() if l.startswith('- ')]),6)
        self.assertEqual(e.count('https://'),2)
        self.assertIn('Last checked: 2026-10-20',e)
        self.assertTrue({'R010','R011'}.issubset({r['review_id'] for r in a['fee_evidence']}))
        import re
        excerpts=re.findall('“(.*?)”',w)
        self.assertEqual(len(excerpts),3)
        for excerpt,r in zip(excerpts,a['quotes']):
            self.assertIn(excerpt,r['review_text'])
            self.assertIn(r['source_url'],w)
    def test_checked_in_artifacts_match_analysis(self):
        a,w,e,entry,_,_=fixture()
        self.assertEqual((ROOT/'weekly_product_pulse.md').read_text(),w)
        self.assertEqual((ROOT/'fee_explainer.md').read_text(),e)
        self.assertEqual(json.loads((ROOT/'demo_examples/notes_entry_example.json').read_text()),entry)
        snippet=(ROOT/'demo_examples/notes_snippet_example.md').read_text()
        self.assertIn(json.dumps(entry,indent=2,ensure_ascii=False),snippet)
        msg=BytesParser(policy=policy.default).parsebytes((ROOT/'demo_examples/email_draft_example.eml').read_bytes())
        self.assertIn(w,msg.get_content())
        self.assertIn(e,msg.get_content())
        self.assertTrue(str(msg['Subject']).startswith('Weekly Product Pulse + Customer Clarification —'))

    def test_missing_columns(self):
        with self.assertRaises(ValueError): load_csv('date,text\n2026-10-01,hello')
    def test_bad_rows_not_silently_discarded(self):
        for row in ['bad,hello,https://example.com','2026-10-01,,https://example.com','2026-10-01,hi,javascript:bad','2026-10-01,hi,https://']:
            with self.subTest(row=row), self.assertRaises(ValueError):
                load_csv('date,review_text,source_url\n'+row)
    def test_optional_platform(self):
        rows=load_csv('date,review_text,source_url\n2026-10-01,refund renewal,https://example.com')
        self.assertEqual(rows[0]['platform'],'Public feedback')
    def test_empty_and_encoding(self):
        for raw in ['',b'\xff', 'date,review_text,source_url\n']:
            with self.subTest(raw=raw),self.assertRaises(ValueError):load_csv(raw)
    def test_deduplication(self):
        raw='date,review_text,source_url\n'+('2026-10-01,refund renewal,https://example.com\n'*2)
        a=analyze(load_csv(raw),date(2026,10,20))
        self.assertFalse(a['fee_detected'])
    def test_no_mutation_and_label_injection(self):
        rows=load_csv((ROOT/'reviews_sample.csv').read_bytes())
        rows[0]['theme']='Injected sixth theme'
        a=analyze(rows,date(2026,10,20))
        self.assertTrue(all(t in THEMES for t,_ in a['themes']))
        self.assertEqual(rows[0]['theme'],'Injected sixth theme')
    def test_future_and_old_excluded(self):
        rows=load_csv('date,review_text,source_url\n2027-01-01,refund renewal,https://example.com\n2025-01-01,hi,https://example.org')
        self.assertEqual(analyze(rows,date(2026,10,20))['rows'],[])
    def test_insufficient_input(self):
        with self.assertRaises(ValueError): pulse(analyze([],date(2026,10,20)))
    def test_policy_date_not_analysis_date(self):
        a,*_=fixture();a['as_of']='2030-01-01'
        self.assertIn('Last checked: 2026-10-20',fee_explainer(a))
    def test_long_quotes_preserve_word_limit(self):
        rows=load_csv((ROOT/'reviews_sample.csv').read_bytes())
        for r in rows:r['review_text']+=' extra'*2000
        a=analyze(rows,date(2026,10,20))
        self.assertLess(len(pulse(a).split()),250)
    def test_llm_constrained_labels_and_no_mutation(self):
        from types import SimpleNamespace
        from engine import classify_with_llm, classify
        rows=load_csv((ROOT/'reviews_sample.csv').read_bytes())[:1]
        response=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='invent a sixth theme'))])
        with patch('openai.OpenAI') as client:
            client.return_value.chat.completions.create.return_value=response
            labeled=classify_with_llm(rows,'test-not-a-real-key')
            self.assertEqual(labeled[0]['theme'],classify(rows[0]['review_text']))
            self.assertNotIn('theme',rows[0])
            messages=client.return_value.chat.completions.create.call_args.kwargs['messages']
            self.assertIn('untrusted',messages[0]['content'])
    def test_invalid_output_validation(self):
        a,w,e,*_=fixture()
        self.assertTrue(validate_outputs(a,w.replace('“','"'),e+'\n- Extra'))

    def test_canceling_for_dissatisfaction_is_not_fee_confusion(self):
        rows=load_csv('date,review_text,source_url\n2026-10-01,I will cancel my subscription because the voice changed,https://example.com\n2026-10-02,canceling my subscription because answers are poor,https://example.org')
        self.assertFalse(analyze(rows,date(2026,10,20))['fee_detected'])

    def test_billing_errors_not_policy_confusion(self):
        rows=load_csv('date,review_text,source_url\n2026-10-01,charged twice,https://example.com\n2026-10-02,card debit error,https://example.org')
        self.assertFalse(analyze(rows,date(2026,10,20))['fee_detected'])


class ApprovalTests(unittest.TestCase):
    def test_unapproved_client_never_spawns(self):
        *_,entry,subject,body=fixture()
        with patch('workflow.secrets.token_urlsafe') as spawn:
            for approval,digest in [(False,None),(True,'stale')]:
                with self.assertRaises(PermissionError):
                    asyncio.run(call_mcp_tools(entry,subject,body,approved=approval,approved_digest=digest))
            spawn.assert_not_called()
    def test_server_rejects_missing_or_changed_approval(self):
        from mcp_server import authorize
        *_,entry,subject,body=fixture()
        with tempfile.TemporaryDirectory() as d:
            with patch.dict(os.environ,{'REVIEWPULSE_APPROVAL_TOKEN':'secret','REVIEWPULSE_APPROVED_DIGEST':payload_digest(entry,subject,body),'REVIEWPULSE_OUTPUT_DIR':d}):
                with self.assertRaises(PermissionError):authorize(json.dumps(entry),subject,body,'wrong')
                with self.assertRaises(PermissionError):authorize(json.dumps(entry),subject,body+'changed','secret')
                self.assertEqual(list(Path(d).iterdir()),[])
    def test_real_stdio_mcp_and_append(self):
        *_,entry,subject,body=fixture()
        with tempfile.TemporaryDirectory() as d:
            for i in range(2):
                notes,draft=asyncio.run(call_mcp_tools(entry,subject,body,approved=True,
                    approved_digest=payload_digest(entry,subject,body),output_dir=d))
            self.assertEqual(notes.read_text().count('## ReviewTrace entry'),2)
            msg=BytesParser(policy=policy.default).parsebytes(draft.read_bytes())
            self.assertEqual(str(msg['Subject']),subject)
            self.assertIn(entry['weekly_pulse'].strip(),msg.get_content())
            self.assertIn('Last checked:',msg.get_content())
            self.assertEqual(msg['X-Unsent'],'1')
            self.assertIsNone(msg['To'])
    def test_real_stdio_rejects_unapproved_calls(self):
        async def run():
            from mcp import ClientSession,StdioServerParameters
            from mcp.client.stdio import stdio_client
            with tempfile.TemporaryDirectory() as d:
                env={**os.environ,'REVIEWPULSE_APPROVAL_TOKEN':'','REVIEWPULSE_OUTPUT_DIR':d}
                async with stdio_client(StdioServerParameters(command=sys.executable,args=[str(ROOT/'mcp_server.py')],env=env)) as (r,w):
                    async with ClientSession(r,w) as session:
                        await session.initialize()
                        tools=await session.list_tools()
                        self.assertEqual({t.name for t in tools.tools},{'append_product_notes','create_email_draft'})
                        for tool in tools.tools:
                            result=await session.call_tool(tool.name,{'entry_json':'{}','subject':'x','body':'x','approval_token':''})
                            self.assertTrue(result.isError)
                self.assertEqual(list(Path(d).iterdir()),[])
        asyncio.run(run())


class UITests(unittest.TestCase):
    def test_ui_load_and_approval(self):
        from streamlit.testing.v1 import AppTest
        app=AppTest.from_file(str(ROOT/'app.py')).run(timeout=20)
        self.assertEqual(len(app.exception),0)
        button=next(b for b in app.button if b.label=='Append notes & create draft')
        self.assertTrue(button.disabled)
        app.checkbox[0].check().run()
        self.assertFalse(next(b for b in app.button if b.label=='Append notes & create draft').disabled)
        next(b for b in app.button if b.label=='Append notes & create draft').click().run(timeout=20)
        self.assertEqual(len(app.exception),0)
        self.assertEqual(len(app.session_state['artifacts']),2)
        self.assertTrue(next(b for b in app.button if b.label=='Append notes & create draft').disabled)
        app.date_input[0].set_value(date(2026,10,19)).run()
        self.assertFalse(app.checkbox[0].value)
        self.assertTrue(next(b for b in app.button if b.label=='Append notes & create draft').disabled)

if __name__=='__main__':unittest.main()
