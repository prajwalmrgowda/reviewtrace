"""Collect recent public ChatGPT reviews from Apple's public RSS feed, preserving provenance."""
import argparse
import csv
from datetime import date,datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import requests

APP_ID='6448311069'
FIELDS=['review_id','date','platform','rating','review_text','source_url','review_title','source_feed_url','source_updated_at','retrieved_at']


def parse_feed(data,feed_url,as_of,weeks,retrieved_at):
    rows=[]
    earliest=as_of-timedelta(weeks=weeks)
    for entry in data.get('feed',{}).get('entry',[]):
        if 'content' not in entry or 'im:rating' not in entry:continue
        updated=entry['updated']['label']
        day=datetime.fromisoformat(updated).date()
        if not earliest<=day<=as_of:continue
        review_id=entry['id']['label']
        rows.append({'review_id':'APPLE_'+review_id,'date':day.isoformat(),'platform':'Apple App Store (US)',
            'rating':entry['im:rating']['label'],'review_text':entry['content']['label'],
            'source_url':f'https://apps.apple.com/us/app/chatgpt/id{APP_ID}?see-all=reviews&reviewId={review_id}',
            'review_title':entry.get('title',{}).get('label',''),'source_feed_url':feed_url,
            'source_updated_at':updated,'retrieved_at':retrieved_at})
    return rows


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--country',choices=['us','gb','in'],default='us')
    parser.add_argument('--pages',type=int,default=10)
    parser.add_argument('--as-of',type=date.fromisoformat,default=date(2026,10,20))
    parser.add_argument('--output',type=Path,default=Path('reviews_collected.csv'))
    args=parser.parse_args()
    if not 1<=args.pages<=10:parser.error('pages must be between 1 and 10')
    retrieved=datetime.now(timezone.utc).isoformat()
    snapshot_dir=Path('data/source_snapshots');snapshot_dir.mkdir(parents=True,exist_ok=True)
    rows=[];seen=set();captures=[]
    for page in range(1,args.pages+1):
        url=f'https://itunes.apple.com/{args.country}/rss/customerreviews/page={page}/id={APP_ID}/sortby=mostrecent/json'
        response=requests.get(url,timeout=25)
        response.raise_for_status()
        data=response.json()
        path=snapshot_dir/f'apple_{args.country}_page_{page}.json'
        path.write_bytes(response.content)
        captures.append({'url':url,'path':str(path),'sha256':hashlib.sha256(response.content).hexdigest()})
        batch=parse_feed(data,url,args.as_of,12,retrieved)
        for row in batch:
            row['platform']=f'Apple App Store ({args.country.upper()})'
            row['source_url']=row['source_url'].replace('/us/app/','/'+args.country+'/app/')
        for row in batch:
            identity=row['review_id']
            if identity not in seen and row['review_text'].strip():rows.append(row);seen.add(identity)
        print(f'Page {page}: {len(batch)} in-window reviews')
    # Stable selection: all captured in-window entries; no fee/rating filtering.
    with args.output.open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS);writer.writeheader();writer.writerows(rows)
    manifest={'product':'ChatGPT','app_id':APP_ID,'storefront':args.country.upper(),'sort':'mostrecent','as_of':args.as_of.isoformat(),
        'weeks':12,'date_semantics':'Apple RSS updated timestamp; may reflect a review edit, not original publication',
        'retrieved_at':retrieved,'row_count':len(rows),'captures':captures}
    Path(f'data/collection_manifest_{args.country}.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(f'Saved {len(rows)} reviews to {args.output}')

if __name__=='__main__':main()
