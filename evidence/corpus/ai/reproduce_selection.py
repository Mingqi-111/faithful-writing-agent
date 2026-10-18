import urllib.request, urllib.parse, csv, io, json, pathlib, hashlib, concurrent.futures, re
import argparse
parser=argparse.ArgumentParser(description='Reproduce the 50-record selection; full text is written only under private/. No remote code is executed.')
parser.add_argument('--output-dir',required=True)
args=parser.parse_args()
BASE=pathlib.Path(args.output_dir).expanduser().resolve()
(BASE/'private').mkdir(parents=True,exist_ok=True)
(BASE/'public').mkdir(parents=True,exist_ok=True)
COMMIT='b90072cd218b6ebdbd1d1478ce6e439677f18192'
EXPECTED_SHA256={'CReD_news_claude-3.5-haiku.csv': 'b4d98fcfc5ac5ceab261e5a4e155ea2fef5c03429dbc80d21f4cbae05ca55345', 'CReD_composition_claude-3.5-haiku.csv': 'e8b767a27efe0c81b085ac1c3707f0426090017686dc12de8442f2d5cbf6fda7', 'CReD_news_deepseek-r1.csv': '33d0075747245f5bff3b3acdf3c402e3d0210e81f9696f02e06e7bb2fc6b3bf5', 'CReD_composition_deepseek-r1.csv': 'cb977c507be5f6eb45cc44ed633d40995e3e577dc6c90cb6a080531b5a94a9ac', 'CReD_news_deepseek-v3.csv': '4028167e37acb5379a476ecc78a5c65e19578e5ab5673a47ebf5b19e48bd7607', 'CReD_composition_deepseek-v3.csv': '7f4bc0f34c1c6d42cd0ba9e5b626d95f4a1ba1eb8a57cd24e028feae78e5d08f', 'CReD_news_doubao-1.5-pro.csv': '8a6640f830356b382e9b0afb5e7d9d61ae7c3e9a8857a68b5fa42f3b30e831c3', 'CReD_composition_doubao-1.5-pro.csv': '6fcc5f1f57e5859d93aeb71f8497e6b7c3dd71130123c8ea8e1b8ace8ead7f58', 'CReD_news_gemini-2.5-flash.csv': '5ba96ee5bc80179f0728977f4d9eb42c37f038acf9c950cd88b97f43c602aa76', 'CReD_composition_gemini-2.5-flash.csv': 'c6dd271e5dcbac76f034ffaa93b7952cd61f865f138a2c011561798b4c2a97ca', 'CReD_news_gpt-4o.csv': '00ca9625b5f57f3aa1ce235375661b21fcc0aecf318d99208c43f70d4293bc0c', 'CReD_composition_gpt-4o.csv': '0a884e3c1aac117b2034cb55b29246bc024f68d2d62eecfd23bfeb2b39975e73', 'CReD_news_qwen-3.csv': '9d59244e12cb486793134391572a9bfb7117e9ed199669a7e64dcc2bd7da93aa', 'CReD_composition_qwen-3.csv': 'd554af0ae846e1bf7196dd7251c6ae6cc6ff8921dec3751185612c7f05eca7e3'}
SEED='faithful-writing-ai-corpus-2026-10-18-v1'
MODELS=['claude-3.5-haiku','deepseek-r1','deepseek-v3','doubao-1.5-pro','gemini-2.5-flash','gpt-4o','qwen-3']
DOMAINS=['news','composition']
(BASE/'private'/'sources').mkdir(exist_ok=True)
def fetch(spec):
 model,domain=spec
 fn='CReD_'+domain.replace(' ','_')+'_'+model+'.csv'; path='benchmark data/'+domain+'/'+fn
 url='https://raw.githubusercontent.com/HeraldofLight/C-ReD/'+COMMIT+'/'+urllib.parse.quote(path)
 dest=BASE/'private'/'sources'/fn
 if dest.exists(): b=dest.read_bytes()
 else:
  b=urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Codex dataset research'}),timeout=120).read();dest.write_bytes(b)
 rows=list(csv.DictReader(io.StringIO(b.decode('utf-8-sig'))))
 sha=hashlib.sha256(b).hexdigest()
 if sha!=EXPECTED_SHA256[fn]: raise ValueError('Source file SHA mismatch: '+fn)
 eligible=[]
 for rownum,r in enumerate(rows,2):
  txt=r.get('text',''); n=len(re.sub(r'\s','',txt))
  if r.get('label')!='0' or r.get('attribution')!=model or not 500<=n<=800: continue
  h=hashlib.sha256((SEED+'|'+path+'|'+str(rownum)).encode()).hexdigest()
  eligible.append((h,rownum,r,n))
 return model,domain,path,sha,len(rows),sorted(eligible)
results=list(concurrent.futures.ThreadPoolExecutor(max_workers=6).map(fetch,[(m,d) for m in MODELS for d in DOMAINS]))
by={(m,d):(m,d,p,s,n,e) for m,d,p,s,n,e in results}
selected=[]; used=set(); counts=[]
for model in MODELS:
 for domain in DOMAINS:
  m,d,p,s,total,eligible=by[model,domain]
  count=(4 if model=='gpt-4o' else 3) if domain=='news' else 4
  chosen=0
  for rank,(h,rownum,r,n) in enumerate(eligible,1):
   original=(domain,r.get('original_id',''))
   if original[1] and original in used: continue
   used.add(original)
   identifier='AI-'+str(len(selected)+1).zfill(3)
   item={'id':identifier,'dataset':'C-ReD','domain':domain,'model':model,'repo_url':'https://github.com/HeraldofLight/C-ReD','commit':COMMIT,'source_file':p,'source_file_sha256':s,'source_csv_record_1based_including_header':rownum,'source_dataset_id':r['id'],'original_id':r.get('original_id'),'source_text_sha256':hashlib.sha256(r['text'].encode()).hexdigest(),'non_whitespace_chars':n,'sampling_hash':h,'eligible_rank':rank,'publisher_label':r['label'],'publisher_attribution':r['attribution'],'generation_provenance':'publisher_labeled_ai_not_independently_verified','generation_confidence_note':'Dataset publisher identifies generator in row attribution and organizes AI files by model; no generation logs were independently checked.','source_url':'https://github.com/HeraldofLight/C-ReD/blob/'+COMMIT+'/'+urllib.parse.quote(p),'private_text':r['text'],'private_source_record':r}
   selected.append(item);chosen+=1
   if chosen==count: break
  counts.append({'model':model,'domain':domain,'total_records':total,'eligible_records':len(eligible),'sampled':chosen,'file_sha256':s,'source_file':p})
  if chosen!=count: raise ValueError((model,domain,chosen,count))
(BASE/'private'/'selected_fulltext.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in selected))
(BASE/'public'/'sampling.json').write_text(json.dumps({'seed':SEED,'commit':COMMIT,'algorithm':'Within each model/domain, filter publisher label=0 and attribution=model and 500<=non-whitespace chars<=800. Sort by SHA256(seed|source_path|CSV record index including header). Select first quota; skip repeated nonempty (domain,original_id). Model/domain iteration follows lists stored here. No lexical/style score used in eligibility or ordering.','models':MODELS,'domains':DOMAINS,'quotas':'3 news + 4 composition per model; gpt-4o has one additional news item.','counts':counts,'total':len(selected)},ensure_ascii=False,indent=2))
for start in range(0,50,10):
 subset=selected[start:start+10]
 (BASE/'private'/f'review_batch_{start//10+1}.txt').write_text('\n\n'.join(x['id']+' | '+x['model']+' | '+x['domain']+' | '+str(x['non_whitespace_chars'])+' chars\nTITLE/PROMPT: '+str(x['private_source_record'].get('prompt',''))+'\nFULL TEXT:\n'+x['private_text'] for x in subset))
print(json.dumps({'selected':len(selected),'counts':counts},ensure_ascii=False,indent=2))
