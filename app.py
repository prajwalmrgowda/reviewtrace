"""ReviewTrace: review evidence, bounded outputs, explicit approval, real local MCP."""
import asyncio
import logging
import os
from datetime import date
from pathlib import Path
import tempfile
import streamlit as st
from engine import (load_csv, analyze, pulse, fee_explainer, validate_outputs,
                    OFFICIAL, FEE, EXPLANATION, classify_with_llm)
from workflow import call_mcp_tools, payload_digest
from google_docs import document_id as parse_document_id, check_document

ROOT=Path(__file__).resolve().parent
st.set_page_config(page_title='ReviewTrace', page_icon='📊', layout='wide')
st.markdown('''<style>
.block-container{padding-top:2.5rem;max-width:1140px}
h1,h2,h3{letter-spacing:-.025em}
[data-testid="stMetric"]{background:#f3f6fa;border:1px solid #dae2ed;border-radius:12px;padding:18px;color:#14243b}
[data-testid="stMetricValue"]{font-weight:700}
</style>''',unsafe_allow_html=True)
st.caption('PRODUCT INTELLIGENCE / CUSTOMER SUPPORT')
st.title('ReviewTrace')
st.write('Turn customer feedback into a weekly product brief and a sourced support answer.')
st.info('Real MCP protocol · Choose local notes or Google Docs below · Email stays a local .eml draft · No email sending')
sample=(ROOT/'reviews_sample.csv').read_bytes()
with st.sidebar:
    st.header('Notes connection')
    notes_mode=st.radio('Notes destination',['Local simulation','Google Docs'])
    notes_destination='google_docs' if notes_mode=='Google Docs' else 'local'
    doc_id=''
    credentials_info=None
    connection_error=None
    if notes_destination=='google_docs':
        default_doc=os.environ.get('REVIEWPULSE_GOOGLE_DOC_ID','')
        try:
            credentials_info=dict(st.secrets['google_service_account']) if 'google_service_account' in st.secrets else None
            default_doc=default_doc or st.secrets.get('google_doc_id','')
        except FileNotFoundError:
            pass
        doc_value=st.text_input('Google Doc URL or ID',value=default_doc)
        st.caption('Setup: GOOGLE_DOCS_SETUP.md. Enable Docs API, configure service-account credentials, then share this Doc with its email as Editor.')
        try:
            doc_id=parse_document_id(doc_value)
            if not credentials_info and not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS') and not os.environ.get('REVIEWPULSE_GOOGLE_CREDENTIALS_JSON'):
                connection_error='Google credentials are not configured. Follow GOOGLE_DOCS_SETUP.md.'
        except ValueError as exc:
            connection_error=str(exc)
        if connection_error: st.warning(connection_error)
        if st.button('Check Google Docs connection',disabled=bool(connection_error)):
            try:
                metadata=check_document(doc_id,credentials_info)
                st.success('Readable Google Doc: '+metadata['title'])
                st.caption('Read access verified. Edit access will be checked when an approved append is requested.')
            except (ValueError,RuntimeError) as exc:
                st.error(str(exc))
    st.header('Analysis workspace')
    upload=st.file_uploader('Reviews CSV',type='csv',help='UTF-8, up to 5 MB / 10,000 reviews. Required: date, review_text, source_url.')
    asof=st.date_input('Analysis end date',value=date(2026,10,20))
    weeks=st.select_slider('Lookback in weeks',options=[8,9,10,11,12],value=12)
    st.caption('Sample window ends 20 October 2026. Adjust for your own reviews.')
    api_key=st.text_input('Optional OpenAI API key',type='password',help='Explicitly run labeling below. Review text is sent to OpenAI only when you click that button.')
    run_llm=st.button('Analyze with OpenAI',disabled=not api_key)
    st.download_button('Download sample CSV',sample,file_name='reviews_sample.csv',mime='text/csv')
with st.expander('Evidence, method and privacy'):
    st.write('The bundled CSV has 500 newly collected US App Store reviews plus 12 legacy app-store/social entries. Apple review text, ratings and updated timestamps are backed by saved feed snapshots. Legacy dates are not all verified. The 500 new reviews cover 17–19 October within the selected 12-week window; they do not span all 12 weeks. Most positive, non-English or unmatched reviews remain unclassified by the issue-focused offline rules. Duplicate text from the same source is counted once.')
    st.write('Offline mode groups reviews using five fixed keyword categories; it is not semantic clustering or vector RAG. Optional OpenAI mode assigns the same bounded categories. Policy guidance comes from a curated official-source snapshot, not live retrieval. Raw reviews are untrusted data and cannot invoke tools.')
try:
    rows=load_csv(upload.getvalue() if upload else sample)
    import hashlib
    dataset_key=hashlib.sha256((upload.getvalue() if upload else sample)).hexdigest()
    if run_llm:
        try:
            with st.spinner('Labeling feedback with OpenAI…'):
                labeled=classify_with_llm([dict(r) for r in rows],api_key)
            st.session_state['labels']=(dataset_key,labeled)
        except Exception:
            st.warning('OpenAI labeling failed. Using offline categories; check your credentials and connectivity before retrying.')
            st.session_state.pop('labels',None)
    saved=st.session_state.get('labels')
    llm_active=bool(saved and saved[0]==dataset_key)
    if llm_active: rows=saved[1]
    a=analyze(rows,asof,weeks)
except ValueError as exc:
    st.error(str(exc)); st.stop()
st.caption('Analysis method: '+('OpenAI category labeling' if llm_active else 'Offline keyword grouping'))
cols=st.columns(3)
cols[0].metric('Reviews in window',len(a['rows']))
cols[1].metric('Themes',len(a['themes']))
cols[2].metric('Renewal / refund evidence',len(a['fee_evidence']))
if not a['rows']:
    st.warning('No reviews in the selected window. Choose another date or upload recent feedback.'); st.stop()
insights,brief,support,actions=st.tabs(['Review intelligence','Weekly pulse','Fee explainer','Approve & export'])
with insights:
    st.subheader('What customers are reporting')
    for name,count in a['themes']:
        st.progress(count/len(a['rows']),text=f'{name} · {count} reviews')
    st.caption('Top three: '+ ' · '.join(t for t,_ in a['top']))
    st.caption(f'{sum(r["theme"]=="Unclassified" for r in a["rows"])} unclassified reviews. Each classified review has one category.')
    st.markdown('#### Three customer voices')
    for q in a['quotes']:
        st.text(q['review_text'])
        st.caption(f'{q["review_id"]} · {q["platform"]} · {q["date"]}')
        st.link_button('View review source',q['source_url'])
    if a['fee_detected']:
        st.success('Recurring fee issue: '+FEE)
        for q in a['fee_evidence']:
            st.text(f'{q["review_id"]}: {q["review_text"]}')
            st.link_button('Fee evidence source',q['source_url'])
    else: st.warning('Need two distinct reviews connecting renewal/cancellation to charges/refunds to establish recurrence.')
try:
    weekly=pulse(a)
    explanation=fee_explainer(a)
except ValueError as exc:
    st.warning(str(exc)); st.stop()
errors=validate_outputs(a,weekly,explanation)
with brief:
    st.subheader('Weekly product pulse')
    st.markdown(weekly)
    st.caption(f'{len(weekly.split())} words · limit: under 250')
    st.download_button('Download weekly pulse',weekly,file_name='weekly_product_pulse.md')
with support:
    st.subheader('Reusable support snippet')
    st.markdown(explanation)
    st.download_button('Download fee explainer',explanation,file_name='fee_explainer.md')
with actions:
    st.subheader('Review, approve, then create')
    if errors:
        st.error('Outputs are incomplete: '+'; '.join(errors)); st.stop()
    st.success('Output checks passed: ≤5 themes · top 3 · 3 quotes · recurring fee evidence · <250 words · ≤6 bullets · 2 official links · policy date')
    entry={'date':a['as_of'],'top_themes':[{'theme':t,'count':c} for t,c in a['top']],
           'weekly_pulse':weekly,'identified_fee_issue':FEE,'explanation_bullets':EXPLANATION,'source_links':OFFICIAL}
    subject=f'Weekly Product Pulse + Customer Clarification — ChatGPT Mobile ({a["as_of"]})'
    body=f'{weekly}\n\nReusable support snippet\n\n{explanation}'
    digest=payload_digest(entry,subject,body,notes_destination=notes_destination,document_id=doc_id)
    if notes_destination=='google_docs':
        st.write('Notes destination: Google Docs (real remote append). Email destination: local .eml draft.')
        if doc_id: st.link_button('Open target Google Doc',f'https://docs.google.com/document/d/{doc_id}/edit')
        if connection_error: st.error(connection_error)
    else:
        st.caption('Notes destination: local Markdown simulation. Email destination: local .eml draft.')
    with st.expander('Preview exact notes entry and email draft',expanded=True):
        st.json(entry)
        st.text(subject)
        st.text(body)
    approval_text=('I reviewed this exact payload and approve appending it to the Google Doc shown above and creating a local email draft.' if notes_destination=='google_docs' else 'I reviewed this exact payload and approve appending local notes and creating a local email draft.')
    approved=st.checkbox(approval_text,key='approval_'+digest)
    if st.button('Append notes & create draft',type='primary',disabled=not approved or bool(connection_error) or st.session_state.get('completed')==digest):
        try:
            if 'output_dir' not in st.session_state:
                st.session_state.output_dir=tempfile.mkdtemp(prefix='reviewtrace-')
            paths=asyncio.run(call_mcp_tools(entry,subject,body,approved=approved,approved_digest=digest,output_dir=st.session_state.output_dir,notes_destination=notes_destination,document_id=doc_id,google_credentials_info=credentials_info))
            st.session_state['artifacts']=[(p.name,p.read_bytes()) for p in paths]
            st.session_state['completed']=digest
            st.rerun()
        except Exception:
            logging.exception('Approval-gated local MCP workflow failed')
            st.error('MCP actions failed. Notes may already have been appended; inspect the target Google Doc or local output before retrying. Check credentials, document sharing and server logs.')
    if st.session_state.get('completed')==digest:
        st.success('Real MCP calls completed. '+('Google Doc updated' if notes_destination=='google_docs' else 'Local notes appended')+' and local email draft created. Nothing sent.')
        for name,data in st.session_state.get('artifacts',[]):
            st.download_button('Download '+name,data,file_name=name,mime='message/rfc822' if name.endswith('.eml') else 'text/markdown')
    st.caption('Google Docs mode appends remotely using service-account authentication. Local mode simulates notes. Email is always a local draft; Gmail is not connected. Download local artifacts before leaving.')
