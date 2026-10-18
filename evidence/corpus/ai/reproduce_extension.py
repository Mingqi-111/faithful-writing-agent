import pathlib,json,csv,hashlib,re,shutil
import argparse
parser=argparse.ArgumentParser(description='Reproduce the 35-item extension after reproduce_selection.py; writes article text only under private/.')
parser.add_argument('--output-dir',required=True)
P=pathlib.Path(parser.parse_args().output_dir).expanduser().resolve()
old=[json.loads(l) for l in (P/'private'/'selected_fulltext.jsonl').read_text().splitlines()]
seed='faithful-writing-ai-corpus-2026-10-18-v1';used={(x['domain'],x['original_id']) for x in old};selected=[];counts=[]
for model in dict.fromkeys(x['model'] for x in old):
 taken=0
 for domain in ['composition','news']:
  ref=next(x for x in old if x['model']==model and x['domain']==domain)
  data=(P/'private'/'sources'/pathlib.Path(ref['source_file']).name).read_bytes();assert hashlib.sha256(data).hexdigest()==ref['source_file_sha256']
  rows=list(csv.DictReader(data.decode('utf-8-sig').splitlines(keepends=True)));eligible=[]
  for rownum,r in enumerate(rows,2):
   n=len(re.sub(r'\s','',r['text']))
   if r['label']!='0' or r['attribution']!=model or not 500<=n<=800:continue
   h=hashlib.sha256((seed+'|'+ref['source_file']+'|'+str(rownum)).encode()).hexdigest();eligible.append((h,rownum,r,n))
  pool=0;newcount=0
  for rank,(h,rownum,r,n) in enumerate(sorted(eligible),1):
   key=(domain,r.get('original_id',''))
   if key[1] and key in used:continue
   pool+=1
   if taken>=5:continue
   used.add(key);item={k:v for k,v in ref.items() if k not in ['private_text','private_source_record','review']}
   item.update({'id':'AI-'+str(51+len(selected)).zfill(3),'source_csv_record_1based_including_header':rownum,'source_dataset_id':r['id'],'original_id':r.get('original_id'),'source_text_sha256':hashlib.sha256(r['text'].encode()).hexdigest(),'non_whitespace_chars':n,'sampling_hash':h,'eligible_rank':rank,'sampling_phase':2,'private_text':r['text'],'private_source_record':r})
   selected.append(item);newcount+=1;taken+=1
  counts.append({'model':model,'domain':domain,'additional_sampled':newcount,'remaining_eligible_at_scan_start':pool})
  if taken>=5:break
 if taken<5:raise ValueError((model,taken))
(P/'private'/'phase2_selected_fulltext.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in selected))
(P/'public'/'phase2_sampling.json').write_text(json.dumps({'phase':2,'requested_additional_max':35,'count':len(selected),'seed':seed,'rule':'Freeze phase 1. For each same model in original order, take five new items by the same original hash ordering and length/label/attribution filters. Prefer composition after observing more obvious editable issues in phase 1; if eligible unused composition is exhausted, fill remaining quota with news. Skip all previously used (domain,original_id). No keyword/style regex is used. Selection after reading therefore belongs to an explicitly issue-enriched development study, not a prevalence sample.','counts':counts},ensure_ascii=False,indent=2))
for start in range(0,len(selected),7):
 (P/'private'/f'phase2_batch_{start//7+1}.txt').write_text('\n\n'.join(x['id']+' | '+x['model']+' | '+x['domain']+' | '+str(x['non_whitespace_chars'])+' chars\nTITLE/PROMPT: '+x['private_source_record']['prompt']+'\nFULL TEXT:\n'+x['private_text'] for x in selected[start:start+7]))
print(json.dumps({'count':len(selected),'counts':counts},ensure_ascii=False,indent=2))
