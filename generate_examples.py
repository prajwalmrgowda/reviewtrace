"""Regenerate reviewable submission artifacts; MCP writes require explicit CLI approval."""
import argparse
import asyncio
from datetime import date
import json
import tempfile
from pathlib import Path
from engine import load_csv, analyze, pulse, fee_explainer, validate_outputs, FEE, EXPLANATION, OFFICIAL
from workflow import call_mcp_tools, payload_digest

ROOT=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approve-local-demo',action='store_true',help='Explicitly approve the printed payload for local MCP notes/draft writes')
    args=parser.parse_args()
    a=analyze(load_csv((ROOT/'reviews_sample.csv').read_bytes()),date(2026,10,20))
    weekly=pulse(a);explanation=fee_explainer(a)
    errors=validate_outputs(a,weekly,explanation)
    if errors:raise ValueError('; '.join(errors))
    entry={'date':a['as_of'],'top_themes':[{'theme':t,'count':c} for t,c in a['top']],
           'weekly_pulse':weekly,'identified_fee_issue':FEE,'explanation_bullets':EXPLANATION,'source_links':OFFICIAL}
    subject=f'Weekly Product Pulse + Customer Clarification — ChatGPT Mobile ({a["as_of"]})'
    body=weekly+'\n\nReusable support snippet\n\n'+explanation
    print(json.dumps({'notes':entry,'subject':subject,'body':body},indent=2,ensure_ascii=False))
    if not args.approve_local_demo:
        print('Preview only. No files written. After review, pass --approve-local-demo to run local MCP tools.')
        return
    demo=ROOT/'demo_examples'
    demo.mkdir(exist_ok=True)
    (ROOT/'weekly_product_pulse.md').write_text(weekly)
    (ROOT/'fee_explainer.md').write_text(explanation)
    with tempfile.TemporaryDirectory(prefix='reviewtrace-examples-') as output:
        paths=asyncio.run(call_mcp_tools(entry,subject,body,approved=True,
            approved_digest=payload_digest(entry,subject,body),output_dir=output))
        (demo/'notes_entry_example.json').write_text(json.dumps(entry,indent=2,ensure_ascii=False)+'\n')
        (demo/'notes_snippet_example.md').write_text(paths[0].read_text())
        (demo/'email_draft_example.eml').write_bytes(paths[1].read_bytes())
    print(f'Validated: {len(weekly.split())} words; {len(a["themes"])} themes; three quotes; six fee bullets; two official links.')

if __name__=='__main__':main()
