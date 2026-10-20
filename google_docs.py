"""Google Docs REST adapter. No write occurs until called by an approved MCP tool."""
import json
import os
import re
from urllib.parse import urlparse

SCOPE='https://www.googleapis.com/auth/documents'


def document_id(value):
    value=(value or '').strip()
    if value.startswith('https://'):
        url=urlparse(value)
        match=re.fullmatch(r'/document/(?:u/\d+/)?d/([\w-]+)(?:/.*)?',url.path)
        if url.hostname!='docs.google.com' or not match:
            raise ValueError('Enter a Google Docs URL or document ID')
        value=match.group(1)
    if not re.fullmatch(r'[A-Za-z0-9_-]{10,200}',value):
        raise ValueError('Enter a valid Google Docs document ID or URL')
    return value


def authorized_session(credentials_info=None):
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import AuthorizedSession
        info=credentials_info
        if info is None and os.environ.get('REVIEWPULSE_GOOGLE_CREDENTIALS_JSON'):
            info=json.loads(os.environ['REVIEWPULSE_GOOGLE_CREDENTIALS_JSON'])
        if info:
            creds=service_account.Credentials.from_service_account_info(dict(info),scopes=[SCOPE])
        else:
            path=os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
            if not path:
                raise ValueError('Configure GOOGLE_APPLICATION_CREDENTIALS or the google_service_account Streamlit secret')
            creds=service_account.Credentials.from_service_account_file(path,scopes=[SCOPE])
        # Auth token requests and document requests have bounded waits. No automatic POST replay.
        return AuthorizedSession(creds,refresh_timeout=10,max_refresh_attempts=0)
    except ImportError as exc:
        raise ValueError('Google dependencies missing. Run .venv/bin/python -m pip install -r requirements.txt') from exc
    except ValueError:
        raise ValueError('Google credentials are missing or invalid. See GOOGLE_DOCS_SETUP.md; never paste keys into chat.') from None
    except Exception:
        raise ValueError('Could not load Google credentials. Check your local credential file or Streamlit secrets.') from None


def check_response(response):
    status=response.status_code
    if not 200<=status<300:
        messages={401:'Google authentication failed. Check the service-account credentials.',
                  403:'Google access denied. Enable the Docs API and share the document with the service-account email as Editor.',
                  404:'Google Doc not found or not shared with this service account.',
                  429:'Google rate limit reached. Wait before retrying; inspect the document for a previous append first.'}
        message=messages.get(status,f'Google Docs request failed (HTTP {status}). Inspect the document before retrying.')
        # Surface Google's machine-readable reason, never raw response bodies or credentials.
        reasons=[]
        try:
            error=response.json().get('error',{})
            for item in error.get('details',[]) + error.get('errors',[]):
                reason=item.get('reason','')
                if isinstance(reason,str) and re.fullmatch(r'[A-Za-z_]{1,80}',reason):
                    reasons.append(reason)
        except (ValueError,TypeError,AttributeError):
            pass
        if status==403:
            if any(reason in ('SERVICE_DISABLED','accessNotConfigured') for reason in reasons):
                message='Google Docs API is disabled in the project used by the credentials. Enable Google Docs API in the project matching project_id in your JSON key, then wait a few minutes.'
            elif 'ACCESS_TOKEN_SCOPE_INSUFFICIENT' in reasons or 'insufficientPermissions' in reasons:
                message='Google token has insufficient permissions. Restart Streamlit with the correct service-account JSON; this app requests the Docs scope.'
            elif 'rateLimitExceeded' in reasons or 'userRateLimitExceeded' in reasons:
                message='Google API quota exceeded. Wait before retrying; check the project quota in Google Cloud Console.'
        if reasons: message+=' Google reason: '+', '.join(dict.fromkeys(reasons))+'.'
        raise RuntimeError(message)
    try: return response.json()
    except Exception: raise RuntimeError('Google Docs returned an invalid response. Inspect the document before retrying.') from None


def check_document(value,credentials_info=None):
    """Read document metadata only; does not prove edit permission or append text."""
    doc_id=document_id(value)
    try:
        with authorized_session(credentials_info) as session:
            response=session.get(f'https://docs.googleapis.com/v1/documents/{doc_id}',
                                 params={'fields':'documentId,title'},timeout=15)
            result=check_response(response)
        return {'document_id':doc_id,'title':result.get('title','Untitled'),'url':f'https://docs.google.com/document/d/{doc_id}/edit'}
    except (ValueError,RuntimeError):raise
    except Exception:raise RuntimeError('Google connection failed. Check connectivity and credentials; no write was requested.') from None


def append_entry(value,entry):
    doc_id=document_id(value)
    text='\n\nReviewTrace entry '+entry['date']+'\n'+json.dumps(entry,indent=2,ensure_ascii=False)+'\n'
    try:
        with authorized_session() as session:
            response=session.post(f'https://docs.googleapis.com/v1/documents/{doc_id}:batchUpdate',
                json={'requests':[{'insertText':{'endOfSegmentLocation':{},'text':text}}]},timeout=15)
            result=check_response(response)
        if result.get('documentId')!=doc_id:
            raise RuntimeError('Unexpected Google Docs response. Inspect the target document before retrying.')
        return {'destination':'Google Docs','document_id':doc_id,'url':f'https://docs.google.com/document/d/{doc_id}/edit','status':'appended'}
    except (ValueError,RuntimeError):raise
    except Exception:raise RuntimeError('Google Docs connection failed; append status is unknown. Inspect the document before retrying to avoid duplicates.') from None
