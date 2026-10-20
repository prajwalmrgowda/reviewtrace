"""Approval-bound real MCP client. Google Docs or local notes; local email draft only, no send capability."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parent


def payload_digest(entry, subject, body, *, notes_destination="local", document_id=""):
    return hashlib.sha256(json.dumps([entry, subject, body, notes_destination, document_id], sort_keys=True, ensure_ascii=False).encode()).hexdigest()


async def call_mcp_tools(entry, subject, body, *, approved=False, approved_digest=None, output_dir=None,
                         notes_destination="local", document_id="", google_credentials_info=None):
    if notes_destination not in ('local','google_docs'): raise ValueError('Unknown notes destination')
    if notes_destination=='google_docs':
        from google_docs import document_id as parse_document_id
        document_id=parse_document_id(document_id)
    elif document_id:
        raise ValueError('Local destination cannot have a Google Doc ID')
    digest = payload_digest(entry, subject, body, notes_destination=notes_destination, document_id=document_id)
    if approved is not True or approved_digest != digest:
        raise PermissionError('Explicit approval of the current exact payload is required')
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    token = secrets.token_urlsafe(32)
    env = {**os.environ, 'REVIEWPULSE_APPROVAL_TOKEN': token,
           'REVIEWPULSE_APPROVED_DIGEST': digest,
           'REVIEWPULSE_OUTPUT_DIR': str(output_dir or ROOT/'outputs')}
    env['REVIEWPULSE_NOTES_DESTINATION']=notes_destination
    env['REVIEWPULSE_GOOGLE_DOC_ID']=document_id
    if google_credentials_info is not None:
        env['REVIEWPULSE_GOOGLE_CREDENTIALS_JSON']=json.dumps(dict(google_credentials_info))
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT/'mcp_server.py')], cwd=str(ROOT), env=env)
    results=[]
    async with asyncio.timeout(60):
        async with stdio_client(params) as (reader, writer):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                for name in ('append_product_notes', 'create_email_draft'):
                    result=await session.call_tool(name, {'entry_json':json.dumps(entry, ensure_ascii=False),
                        'subject':subject, 'body':body, 'approval_token':token})
                    if result.isError:
                        raise RuntimeError(f'{name} failed; earlier actions may already have completed: {result.content}')
                    results.append(Path(json.loads(result.content[0].text)['path']))
    return tuple(results)
