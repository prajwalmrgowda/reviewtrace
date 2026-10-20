"""Actual MCP stdio tools with process-scoped approval, Google Docs or local notes; local email draft."""
from pathlib import Path
import hmac
import json
import os
from email.message import EmailMessage
from mcp.server.fastmcp import FastMCP
from workflow import payload_digest
from engine import OFFICIAL, EXPLANATION, FEE, LAST_CHECKED

mcp = FastMCP('ReviewTrace Tools')


def authorize(entry_json, subject, body, approval_token):
    expected=os.environ.get('REVIEWPULSE_APPROVAL_TOKEN', '')
    if not expected or not hmac.compare_digest(approval_token, expected):
        raise PermissionError('Missing or invalid human approval token')
    entry=json.loads(entry_json)
    required={'date','top_themes','weekly_pulse','identified_fee_issue','explanation_bullets','source_links'}
    if not isinstance(entry, dict) or set(entry) != required:
        raise ValueError('Notes entry does not match required schema')
    if (not isinstance(entry['top_themes'], list) or len(entry['top_themes']) != 3
        or not all(isinstance(t,dict) and isinstance(t.get('count'),int) and t['count']>0 and isinstance(t.get('theme'),str) for t in entry['top_themes'])
        or not isinstance(entry['weekly_pulse'],str) or not 0<len(entry['weekly_pulse'].split())<250
        or entry['identified_fee_issue'] != FEE or entry['source_links'] != OFFICIAL
        or entry['explanation_bullets'] != EXPLANATION):
        raise ValueError('Invalid generated output in notes entry')
    from datetime import date
    date.fromisoformat(entry['date'])
    if not subject.startswith('Weekly Product Pulse + Customer Clarification —') or '\n' in subject or '\r' in subject:
        raise ValueError('Invalid draft subject')
    if (not body or len(body)>100000 or entry['weekly_pulse'] not in body
        or any(item not in body for item in EXPLANATION + OFFICIAL)
        or f'Last checked: {LAST_CHECKED}' not in body):
        raise ValueError('Draft must contain the pulse and support snippet')
    destination=os.environ.get('REVIEWPULSE_NOTES_DESTINATION','local')
    doc_id=os.environ.get('REVIEWPULSE_GOOGLE_DOC_ID','')
    if destination not in ('local','google_docs'): raise ValueError('Unknown notes destination')
    if not hmac.compare_digest(payload_digest(entry,subject,body,notes_destination=destination,document_id=doc_id), os.environ.get('REVIEWPULSE_APPROVED_DIGEST','')):
        raise PermissionError('Payload changed after approval')
    output=Path(os.environ.get('REVIEWPULSE_OUTPUT_DIR', Path(__file__).parent/'outputs'))
    output.mkdir(parents=True,exist_ok=True)
    return entry, output


@mcp.tool()
def append_product_notes(entry_json: str, subject: str, body: str, approval_token: str) -> str:
    """Append an explicitly approved entry to the approved Google Doc or local Markdown notes."""
    entry,output=authorize(entry_json,subject,body,approval_token)
    if os.environ.get('REVIEWPULSE_NOTES_DESTINATION','local')=='google_docs':
        from google_docs import append_entry
        receipt=append_entry(os.environ.get('REVIEWPULSE_GOOGLE_DOC_ID',''),entry)
        target=output/'google_doc_receipt.json'
        target.write_text(json.dumps(receipt,indent=2),encoding='utf-8')
        return json.dumps({'path':str(target),**receipt})
    target=output/'internal_product_notes.md' 
    with target.open('a',encoding='utf-8') as f:
        f.write('\n\n---\n## ReviewTrace entry '+entry['date']+'\n\n```json\n'+json.dumps(entry,indent=2,ensure_ascii=False)+'\n```\n')
    return json.dumps({'path':str(target),'destination':'local simulation'})


@mcp.tool()
def create_email_draft(entry_json: str, subject: str, body: str, approval_token: str) -> str:
    """Create a LOCAL RFC 822 draft; no Gmail connection or send capability."""
    _,output=authorize(entry_json,subject,body,approval_token)
    msg=EmailMessage()
    msg['Subject']=subject
    msg['X-Unsent']='1'
    msg.set_content(body)
    target=output/'weekly_product_pulse_draft.eml'
    temporary=target.with_suffix('.tmp')
    temporary.write_bytes(msg.as_bytes())
    temporary.replace(target)
    return json.dumps({'path':str(target),'destination':'local simulation'})


if __name__ == '__main__':
    mcp.run(transport='stdio')
