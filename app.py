"""ReviewTrace: source-backed review insights with approval-gated exports."""
import asyncio
import hashlib
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
.block-container{padding-top:2rem;padding-bottom:3rem;max-width:1140px}
h1,h2,h3{letter-spacing:-.025em}
[data-testid="stMetric"]{
    background:var(--secondary-background-color,transparent);
    border:1px solid rgba(128,128,128,.28);border-radius:12px;padding:18px;
}
[data-testid="stMetricValue"]{font-weight:700}
[data-testid="stTabs"] [role="tab"]{min-height:3rem}
@media(max-width:640px){.block-container{padding-top:1.25rem}}
</style>''',unsafe_allow_html=True)
st.caption('CUSTOMER FEEDBACK → PRODUCT INSIGHTS')
st.title('ReviewTrace')
st.write('Understand what customers are saying, prepare a weekly brief, and save it when you’re ready.')
st.markdown('**Start here:** review the insights → read both outputs → approve and save in **4. Save & export**.')
sample=(ROOT/'reviews_sample.csv').read_bytes()
notes_destination='local'
doc_id=''
credentials_info=None
connection_error=None
with st.sidebar:
    st.title('ReviewTrace Workspace')
    st.caption('Choose your reviews, connect your notes, and prepare your update.')
    st.divider()
    st.header('Your reviews')
    st.caption('The sample is ready to explore. Upload a CSV only if you want to use your own reviews.')
    upload=st.file_uploader('Upload your reviews (optional)',type='csv',help='UTF-8 CSV, up to 5 MB / 10,000 rows. Required columns: date, review_text, source_url.')
    asof=st.date_input('Review window ends',value=date(2026,10,20),help='Reviews after this date are excluded. The sample ends on 20 October 2026.')
    weeks=st.select_slider('Look back',options=[8,9,10,11,12],value=12,format_func=lambda value:f'{value} weeks')
    st.download_button('Download sample CSV',sample,file_name='reviews_sample.csv',mime='text/csv')
    st.divider()
    st.subheader('Where to save')
    notes_mode=st.radio('Notes destination',['Local simulation','Google Docs'],help='Local simulation creates a downloadable notes file. Google Docs appends to your connected document after approval.')
    notes_destination='google_docs' if notes_mode=='Google Docs' else 'local'
    if notes_destination=='google_docs':
        default_doc=os.environ.get('REVIEWPULSE_GOOGLE_DOC_ID','')
        try:
            credentials_info=dict(st.secrets['google_service_account']) if 'google_service_account' in st.secrets else None
            default_doc=default_doc or st.secrets.get('google_doc_id','')
        except FileNotFoundError:
            pass
        doc_value=st.text_input('Google Doc URL or ID',value=default_doc)
        try:
            doc_id=parse_document_id(doc_value)
            if not credentials_info and not os.environ.get('GOOGLE_APPLICATION_CREDENTIALS') and not os.environ.get('REVIEWPULSE_GOOGLE_CREDENTIALS_JSON'):
                connection_error='Google credentials are not configured. Open the setup help below.'
        except ValueError as exc:
            connection_error=str(exc)
        if connection_error: st.warning(connection_error)
        if st.button('Check Google Docs connection',disabled=bool(connection_error)):
            try:
                with st.spinner('Checking your document…'):
                    metadata=check_document(doc_id,credentials_info)
                st.session_state['verified_doc']=metadata
                st.session_state.pop('doc_check_error',None)
            except (ValueError,RuntimeError) as exc:
                st.session_state.pop('verified_doc',None)
                st.session_state['doc_check_error']=(doc_id,str(exc))
        verified=st.session_state.get('verified_doc',{})
        if verified.get('document_id')==doc_id and doc_id:
            st.success('Connected: '+verified['title'])
            st.caption('Read access verified. An approved append checks edit access.')
        elif not connection_error:
            connection_error='Check the Google Docs connection before saving.'
            st.info(connection_error)
        check_error=st.session_state.get('doc_check_error')
        if check_error and check_error[0]==doc_id: st.error(check_error[1])
        with st.expander('Google Docs setup help'):
            st.write('Enable Google Docs API in your service-account project. Share the target document with the service-account email as Editor.')
            st.write('Local: set GOOGLE_APPLICATION_CREDENTIALS before starting the app. Hosted: add [google_service_account] in Streamlit Secrets. Full instructions are in GOOGLE_DOCS_SETUP.md in your local project.')
    else:
        st.caption('Creates a local notes download. No Google account is accessed.')
    st.caption('Email is always a downloadable draft. Nothing is sent.')
    with st.expander('Optional: use AI labels'):
        st.write('The app works without an API key. AI mode sends review text to OpenAI when you click the button below.')
        api_key=st.text_input('OpenAI API key',type='password')
        run_llm=st.button('Analyze with OpenAI',disabled=not api_key)
with st.expander('About the sample, method and privacy'):
    st.write('The sample has 500 collected US App Store reviews plus 12 legacy app-store/social entries. The new reviews cover 17–19 October 2026, within the selected 12-week window; they do not span the full window. Apple review text, ratings and updated timestamps have saved feed snapshots. Legacy dates are not all verified.')
    st.write('Offline mode uses five issue-focused keyword categories. General praise, non-English feedback and unmatched reviews can remain unclassified. Optional AI mode labels the same categories. This is not vector search or semantic clustering. The fee guidance uses a curated official-source snapshot, not a live policy check. Reviews are untrusted evidence, never tool instructions.')
try:
    raw=upload.getvalue() if upload else sample
    rows=load_csv(raw)
    dataset_key=hashlib.sha256(raw).hexdigest()
    if run_llm:
        try:
            with st.spinner('Labeling reviews with OpenAI. This may take a few minutes…'):
                labeled=classify_with_llm([dict(r) for r in rows],api_key)
            st.session_state['labels']=(dataset_key,labeled)
        except Exception:
            st.warning('AI labeling could not finish. Offline analysis is ready below; check your API key and connection before trying again.')
            st.session_state.pop('labels',None)
    saved=st.session_state.get('labels')
    llm_active=bool(saved and saved[0]==dataset_key)
    if llm_active: rows=saved[1]
    a=analyze(rows,asof,weeks)
except ValueError as exc:
    st.error(str(exc))
    st.info('Check the CSV columns and dates, then upload the corrected file. You can remove the upload to return to the sample.')
    st.stop()
st.caption(f'{"Your uploaded reviews" if upload else "Sample dataset"} · {weeks}-week window ending {asof:%d %b %Y} · '+('AI labels' if llm_active else 'Offline analysis — no API key needed'))
cols=st.columns(3)
cols[0].metric('Reviews analyzed',len(a['rows']),help='All reviews inside the selected date window, including unclassified feedback.')
cols[1].metric('Issue themes',len(a['themes']),help='Up to five issue categories. Each matched review is counted once.')
cols[2].metric('Fee-related reports',len(a['fee_evidence']),help='Reviews connecting renewal/cancellation with charges or refunds. At least two are required to identify recurrence.')
if not a['rows']:
    st.warning('No reviews match this date window. Change the end date or lookback in the sidebar.');st.stop()
insights,brief,support,actions=st.tabs(['1. Review insights','2. Weekly pulse','3. Fee explainer','4. Save & export'])
with insights:
    st.subheader('What stands out')
    st.write('These are the most common issue categories in this sample. Counts show reports, not verified product defects.')
    for rank,(name,count) in enumerate(a['themes'],1):
        st.progress(count/len(a['rows']),text=f'{rank}. {name} · {count} reviews')
    unclassified=sum(r['theme']=='Unclassified' for r in a['rows'])
    st.caption(f'{unclassified} of {len(a["rows"])} reviews did not match these issue categories. They remain in the total; they are not assumed to be negative.')
    st.markdown('#### Three customer voices')
    for q in a['quotes']:
        with st.container(border=True):
            st.text(q['review_text'])
            st.caption(f'{q["platform"]} · {q["date"]} · {q["review_id"]}')
            st.link_button('View review source',q['source_url'])
    st.markdown('#### Is there recurring fee confusion?')
    if a['fee_detected']:
        st.success(f'{len(a["fee_evidence"])} reviews support this issue: {FEE}.')
        st.caption('A small recurring signal in this dataset does not show how common the problem is across all customers.')
        with st.expander('Read the supporting fee reviews'):
            for q in a['fee_evidence']:
                st.text(q['review_text'])
                st.caption(f'{q["review_id"]} · {q["date"]}')
                st.link_button('Fee evidence source',q['source_url'])
    else:
        st.warning('There is not enough recurring fee evidence yet. At least two distinct renewal/charge or cancellation/refund reports are needed.')
    st.info('Next: open **2. Weekly pulse** to review your internal product update.')
try:
    weekly=pulse(a)
    explanation=fee_explainer(a)
except ValueError as exc:
    st.warning(str(exc));st.stop()
errors=validate_outputs(a,weekly,explanation)
with brief:
    st.subheader('Your weekly product update')
    st.caption('An internal brief with the top three themes, sourced customer quotes and three product actions.')
    with st.container(border=True):st.markdown(weekly)
    st.caption(f'{len(weekly.split())} words · under the 250-word limit')
    st.download_button('Download weekly pulse',weekly,file_name='weekly_product_pulse.md',mime='text/markdown')
    st.info('Next: open **3. Fee explainer** to review the customer-facing answer.')
with support:
    st.subheader('A clear answer for customers')
    st.caption('A reusable support snippet tied to the fee issue found in the reviews. Review the policy date before reusing it.')
    with st.container(border=True):st.markdown(explanation)
    st.download_button('Download fee explainer',explanation,file_name='fee_explainer.md',mime='text/markdown')
    st.info('Ready to save both outputs? Open **4. Save & export**.')
with actions:
    st.subheader('Review once. Save when ready.')
    if errors:
        st.error('We cannot save these outputs yet: '+'; '.join(errors))
        st.info('Review the insights and add suitable evidence before trying again.');st.stop()
    st.success('Both outputs passed the assignment checks and are ready for your review.')
    entry={'date':a['as_of'],'top_themes':[{'theme':t,'count':c} for t,c in a['top']],
           'weekly_pulse':weekly,'identified_fee_issue':FEE,'explanation_bullets':EXPLANATION,'source_links':OFFICIAL}
    subject=f'Weekly Product Pulse + Customer Clarification — ChatGPT Mobile ({a["as_of"]})'
    body=f'{weekly}\n\nReusable support snippet\n\n{explanation}'
    digest=payload_digest(entry,subject,body,notes_destination=notes_destination,document_id=doc_id)
    with st.container(border=True):
        st.markdown('**What happens after approval**')
        if notes_destination=='google_docs':
            st.write('1. Append the notes entry to your selected Google Doc.')
            if doc_id:st.link_button('Open target Google Doc',f'https://docs.google.com/document/d/{doc_id}/edit')
            if connection_error:st.warning(connection_error+' Use the sidebar to finish connecting.')
        else:
            st.write('1. Create a downloadable local notes file. To use a real Google Doc, change Notes destination in the sidebar.')
        st.write('2. Create a downloadable email draft with both outputs. Nothing is sent.')
    with st.expander('Preview exactly what will be saved'):
        st.markdown('**Notes entry**')
        st.json(entry)
        st.markdown('**Email draft**')
        st.text(subject)
        st.text(body)
    approval_text=('I reviewed both outputs and approve appending them to the Google Doc shown above and creating a local email draft.' if notes_destination=='google_docs' else 'I reviewed both outputs and approve creating local notes and an email draft.')
    approved=st.checkbox(approval_text,key='approval_'+digest)
    completed=st.session_state.get('completed')==digest
    if not approved and not completed:st.caption('Review tabs 2 and 3, then tick the checkbox to enable saving.')
    if st.button('Append notes & create draft',type='primary',disabled=not approved or bool(connection_error) or completed):
        try:
            if 'output_dir' not in st.session_state:
                st.session_state.output_dir=tempfile.mkdtemp(prefix='reviewtrace-')
            with st.spinner('Saving your notes and preparing the email draft…'):
                paths=asyncio.run(call_mcp_tools(entry,subject,body,approved=approved,approved_digest=digest,output_dir=st.session_state.output_dir,notes_destination=notes_destination,document_id=doc_id,google_credentials_info=credentials_info))
            st.session_state['artifacts']=[(p.name,p.read_bytes()) for p in paths]
            st.session_state['completed']=digest
            st.rerun()
        except Exception:
            logging.exception('Approval-gated MCP workflow failed')
            st.error('Saving could not finish. Notes may already be saved, so check the target document or local output before retrying. Check your connection and credentials if needed.')
    if completed:
        st.success(('Google Doc updated' if notes_destination=='google_docs' else 'Local notes saved')+' and email draft created. Nothing sent.')
        st.markdown('**Download your files**')
        for name,data in st.session_state.get('artifacts',[]):
            label='Download email draft (.eml)' if name.endswith('.eml') else ('Download Google Docs receipt' if name.endswith('.json') else 'Download notes')
            mime='message/rfc822' if name.endswith('.eml') else ('application/json' if name.endswith('.json') else 'text/markdown')
            st.download_button(label,data,file_name=name,mime=mime)
        st.caption('This exact output has already been saved in this session. Change the data or destination to prepare another entry.')
    st.caption('Download local files before closing the app. Google Docs appends use MCP; email stays a local draft. Gmail is not connected.')
