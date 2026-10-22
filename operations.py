"""SupplyOps operating records, append-only events, and deterministic exceptions."""
from copy import deepcopy
from datetime import date
from decimal import Decimal
import hashlib
import json
import re
from core import number, compare, coverage_for, Records
from parsing import validate, parse_support
from workflow import amount, day

REFERENCE_DATE='2026-11-10'
ISSUE_STATUSES=['Open','Awaiting supplier','Internally escalated','Resolved']
SUPPORT_KINDS=['inventory','commitments','terms','alternatives']

def clean(value,limit=200):
    return str(value or '').strip()[:limit]

def identifier(value,label):
    value=clean(value,80).upper()
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9_-]{0,59}',value):
        raise ValueError(label+' must use letters, numbers, hyphens or underscores (up to 60 characters).')
    return value

def checked_date(value,label):
    try: return date.fromisoformat(str(value)).isoformat()
    except (TypeError,ValueError): raise ValueError('Provide a valid '+label+' (YYYY-MM-DD).')

def quantity(value,label,positive=False):
    result=number(value)
    if result is None or (positive and result==0): raise ValueError(label+' must be '+('greater than zero.' if positive else 'a valid nonnegative number.'))
    return format(result.normalize(),'f')

def empty_workspace(reference_date=REFERENCE_DATE):
    return {'version':2,'as_of':checked_date(reference_date,'workspace date'),'orders':{},'events':[],'issues':{},'investigations':[],'support':{},'sample_orders':[]}

def events_for(state,order_id,kind=None):
    return [deepcopy(e) for e in state['events'] if e['order_id']==order_id and (not kind or e['kind']==kind)]

def append_event(state,order_id,kind,effective_on,payload):
    event={'id':f'EVT-{len(state["events"])+1:05d}','sequence':len(state['events'])+1,'order_id':order_id,'kind':kind,'effective_on':effective_on,'payload':deepcopy(payload)}
    state['events'].append(event)
    return event['id']

def create_order(state,record,created_on=None):
    if len(state['orders'])>=100: raise ValueError('This prototype supports up to 100 orders per workspace.')
    raw=deepcopy(record); raw['order_id']=identifier(raw.get('order_id'),'Order reference')
    if raw['order_id'] in state['orders']: raise ValueError('This purchase-order reference already exists.')
    if not clean(raw.get('supplier')) or not clean(raw.get('payment_terms')): raise ValueError('Supplier and agreed payment terms are required.')
    raw['supplier_id']=clean(raw.get('supplier_id')) or 'SUP-'+hashlib.sha256(raw['supplier'].strip().casefold().encode()).hexdigest()[:12].upper()
    if len(raw['supplier_id'])>80: raise ValueError('Supplier reference must be at most 80 characters.')
    for row in raw.get('lines',[]): row['sku']=identifier(row.get('sku'),'Product code')
    po=validate(raw)
    if not po['lines']: raise ValueError('Add at least one product line.')
    created_on=checked_date(created_on or state['as_of'],'order date')
    if created_on>state['as_of']: raise ValueError('The order date cannot be after the workspace date.')
    for row in po['lines']:
        row['quantity']=quantity(row.get('quantity'),'Ordered quantity',True)
        row['unit_price']=quantity(row.get('unit_price'),'Agreed price')
        if not re.fullmatch('[A-Z]{3}',clean(row.get('currency')).upper()): raise ValueError('Enter a three-letter currency such as EUR.')
        row['currency']=row['currency'].upper()
        row['delivery_date']=checked_date(row.get('delivery_date'),'requested delivery date')
        if row['delivery_date']<created_on: raise ValueError('Requested delivery cannot precede the order date.')
    po['created_on']=created_on
    state['orders'][po['order_id']]=po
    state['support'][po['order_id']]={}
    append_event(state,po['order_id'],'order_created',created_on,{'order':po,'note':'Recorded in SupplyOps; not automatically issued to the supplier.'})
    sync_issues(state,po['order_id'])
    return po['order_id']

def current_confirmation(state,order_id):
    po=state['orders'][order_id]
    snapshot={k:po.get(k) for k in ['order_id','supplier_id','supplier','payment_terms']}
    latest={}; sources={}
    for event in sorted(events_for(state,order_id,'confirmation'),key=lambda e:(e['effective_on'],e['sequence'])):
        for line in event['payload']['lines']:
            latest[line['sku']]=deepcopy(line); sources[line['sku']]=event['id']
    snapshot['lines']=[]
    for ordered in po['lines']:
        line=latest.get(ordered['sku'],{'sku':ordered['sku'],'description':ordered.get('description'),'quantity':None,'unit_price':None,'currency':None,'delivery_date':None,'payment_terms':None})
        snapshot['lines'].append(line)
    terms={x.get('payment_terms') for x in snapshot['lines'] if x.get('payment_terms')}
    snapshot['payment_terms']=next(iter(terms)) if len(terms)==1 else 'Mixed terms — see product lines' if terms else None
    snapshot['source_ids']=sources
    snapshot['notes']=' '.join(e['payload'].get('notes','') for e in sorted(events_for(state,order_id,'confirmation'),key=lambda e:(e['effective_on'],e['sequence']))[-1:])
    return snapshot

def received_quantities(state,order_id,by_date=None):
    totals={line['sku']:Decimal(0) for line in state['orders'][order_id]['lines']}
    for event in events_for(state,order_id,'receipt'):
        if by_date and event['effective_on']>by_date: continue
        for line in event['payload']['lines']: totals[line['sku']]+=Decimal(line['quantity'])
    return {sku:str(value) for sku,value in totals.items()}

def record_confirmation(state,order_id,lines,received_on,notes='',attachment=None):
    po=state['orders'][order_id]; received_on=checked_date(received_on,'update received date')
    if not po['created_on']<=received_on<=state['as_of']: raise ValueError('The update date must be between order creation and the workspace date.')
    if not isinstance(lines,list) or not 1<=len(lines)<=30: raise ValueError('Add between one and 30 confirmation lines.')
    ordered={x['sku']:x for x in po['lines']}; seen=set(); checked=[]
    physical=received_quantities(state,order_id,received_on)
    for item in lines:
        sku=identifier(item.get('sku'),'Product code')
        if sku not in ordered or sku in seen: raise ValueError('Confirmation product codes must be unique and belong to this purchase order.')
        seen.add(sku); original=ordered[sku]
        q=quantity(item.get('quantity'),'Confirmed total quantity')
        if Decimal(q)<Decimal(physical[sku]): raise ValueError('The confirmed total cannot be lower than goods already received on that date. Check the quantity or update date.')
        price=item.get('unit_price')
        if item.get('currency') and item['currency']!=original['currency']: raise ValueError('The confirmation currency differs from the order. Reconcile it before recording a unit-price comparison.')
        checked.append({'sku':sku,'description':original.get('description'),'quantity':q,
            'delivery_date':checked_date(item.get('delivery_date'),'expected delivery date'),
            'unit_price':quantity(original['unit_price'] if price in (None,'') else price,'Confirmed unit price'),
            'currency':original['currency'],'payment_terms':clean(item.get('payment_terms')) or po['payment_terms'],'notes':clean(item.get('notes'),500)})
    payload={'lines':checked,'notes':clean(notes,2000)}
    if attachment: payload['attachment']={'filename':clean(attachment['filename']),'size':attachment['size']}
    event_id=append_event(state,order_id,'confirmation',received_on,payload)
    sync_issues(state,order_id)
    return event_id

def record_receipt(state,order_id,lines,receipt_date,note='',attachment=None):
    po=state['orders'][order_id]; receipt_date=checked_date(receipt_date,'receipt date')
    if not po['created_on']<=receipt_date<=state['as_of']: raise ValueError('Receipt date must be between order creation and the workspace date.')
    if not isinstance(lines,list) or not 1<=len(lines)<=30: raise ValueError('Add between one and 30 receipt lines.')
    ordered={x['sku']:x for x in po['lines']}; received=received_quantities(state,order_id); seen=set(); checked=[]
    for row in lines:
        sku=identifier(row.get('sku'),'Product code')
        if sku not in ordered or sku in seen: raise ValueError('Receipt product codes must be unique and belong to this purchase order.')
        seen.add(sku); q=quantity(row.get('quantity'),'Quantity physically received',True)
        if Decimal(received[sku])+Decimal(q)>Decimal(ordered[sku]['quantity']): raise ValueError(f'{sku}: this would exceed the ordered quantity. Receipt was not saved; reconcile the excess with the supplier.')
        expected=ordered[sku]['delivery_date']; source='Original purchase order'
        for event in sorted(events_for(state,order_id,'confirmation'),key=lambda e:(e['effective_on'],e['sequence'])):
            if event['effective_on']>receipt_date: continue
            for promise in event['payload']['lines']:
                if promise['sku']==sku: expected=promise['delivery_date']; source=event['id']
        checked.append({'sku':sku,'quantity':q,'expected_at_receipt':expected,'expected_source':source,'original_requested_date':ordered[sku]['delivery_date']})
    payload={'lines':checked,'note':clean(note,2000)}
    if attachment: payload['attachment']={'filename':clean(attachment['filename']),'size':attachment['size']}
    event_id=append_event(state,order_id,'receipt',receipt_date,payload)
    sync_issues(state,order_id)
    return event_id

def make_case(state,order_id):
    po=deepcopy(state['orders'][order_id]); received=received_quantities(state,order_id)
    confirmation=current_confirmation(state,order_id)
    totals=[]
    for line in po['lines']:
        c=next(x for x in confirmation['lines'] if x['sku']==line['sku']); q=number(c.get('quantity')); physical=Decimal(received[line['sku']])
        totals.append({'sku':line['sku'],'ordered':line['quantity'],'latest_confirmed':c.get('quantity'),'physically_received':str(physical),'outstanding_ordered':str(max(Decimal(0),Decimal(line['quantity'])-physical)),'outstanding_confirmed':str(max(Decimal(0),q-physical)) if q is not None else None,'unconfirmed_quantity':str(max(Decimal(0),Decimal(line['quantity'])-(q or Decimal(0)))),'received_above_confirmed':str(max(Decimal(0),physical-q)) if q is not None else None,'original_requested_date':line['delivery_date'],'current_promised_date':c.get('delivery_date')})
    return {'po':po,'confirmation':confirmation,'delivery_totals':totals,
        'confirmation_history':events_for(state,order_id,'confirmation'),'receipt_history':events_for(state,order_id,'receipt'),
        'received_by_sku':received,'reference_date':state['as_of'],
        'inventory_recorded_sequence':max((e['sequence'] for e in state['events'] if e['order_id']==order_id and e['kind']=='support_updated' and e['payload']['kind']=='inventory'),default=0),
        **deepcopy(state['support'].get(order_id,{}))}

COMMERCIAL_KINDS={'price_change','payment_change'}

def related_issue_ids(state,issue_id):
    """One supply workflow per order/product; commercial decisions stay separate."""
    issue=state['issues'][issue_id]
    if issue['kind'] in COMMERCIAL_KINDS: return [issue_id]
    return [i['id'] for i in state['issues'].values() if i['order_id']==issue['order_id'] and i['sku']==issue['sku'] and i['kind'] not in COMMERCIAL_KINDS and (requires_attention(state,i) or i['id']==issue_id)]

def issue_groups(state,order_id=None):
    pending=[i for i in state['issues'].values() if requires_attention(state,i) and (not order_id or i['order_id']==order_id)]
    groups=[]; seen=set()
    for issue in pending:
        key=(issue['order_id'],issue['sku'],issue['kind'] if issue['kind'] in COMMERCIAL_KINDS else 'supply')
        if key in seen: continue
        seen.add(key); group=deepcopy(issue); ids=related_issue_ids(state,issue['id'])
        group['related_ids']=ids
        group['related_alerts']=[state['issues'][key]['title'] for key in ids if state['issues'][key]['detected']]
        groups.append(group)
    return groups

def evidence_sequence(state,order_id):
    return max((e['sequence'] for e in state['events'] if e['order_id']==order_id and e['kind'] in ('confirmation','receipt','support_updated')),default=0)

def investigation_stale(state,run):
    return run.get('reconciliation_version')!=1 or run['evidence_sequence']<evidence_sequence(state,run['order_id'])

def reconciliation_sentence(total):
    confirmed=amount(total['latest_confirmed']) if total['latest_confirmed'] is not None else 'not recorded'
    text=f'{total["sku"]}: {amount(total["ordered"])} ordered; latest supplier total {confirmed}; {amount(total["physically_received"])} physically received; {amount(total["outstanding_confirmed"])} still promised but not received; {amount(total["unconfirmed_quantity"])} not confirmed by the supplier; {amount(total["outstanding_ordered"])} outstanding against the order.'
    text+=f' Originally due {day(total["original_requested_date"])}; latest promised delivery {day(total["current_promised_date"])}.'
    if number(total.get('received_above_confirmed')):
        text+=' Physical receipts exceed the latest supplier promise; reconcile that inconsistency before relying on the promise balance.'
    return text

def detect_issues(state,order_id):
    case=make_case(state,order_id); po=case['po']; current={x['sku']:x for x in case['confirmation']['lines']}; result=[]
    def add(sku,kind,title,detail,values):
        result.append({'id':f'{order_id}|{sku}|{kind}','order_id':order_id,'sku':sku,'kind':kind,'title':title,'detail':detail,'fingerprint':hashlib.sha256(json.dumps(values,sort_keys=True).encode()).hexdigest()})
    for line in po['lines']:
        sku=line['sku']; c=current[sku]; ordered=Decimal(line['quantity']); received=Decimal(case['received_by_sku'][sku]); remaining=max(Decimal(0),ordered-received)
        confirmed=number(c.get('quantity'))
        if confirmed is None and remaining>0: add(sku,'missing_confirmation','Awaiting supplier confirmation','No supplier commitment is recorded for this product.',[str(remaining)])
        if confirmed is not None:
            if confirmed<ordered: add(sku,'quantity_shortfall','Supplier quantity shortfall',f'{amount(confirmed)} confirmed against {amount(ordered)} ordered; {amount(ordered-confirmed)} units unconfirmed.',[str(ordered),str(confirmed)])
            elif confirmed>ordered: add(sku,'quantity_excess','Supplier quantity above order',f'{amount(confirmed)} confirmed against {amount(ordered)} ordered. Review the proposed extra quantity.',[str(ordered),str(confirmed)])
            if c.get('delivery_date') and c['delivery_date']>line['delivery_date']:
                days=(date.fromisoformat(c['delivery_date'])-date.fromisoformat(line['delivery_date'])).days
                add(sku,'delivery_delay','Supplier delivery delay',f'Requested {day(line["delivery_date"])}; supplier now promises {day(c["delivery_date"])} ({days} days later).',[line['delivery_date'],c['delivery_date']])
            if number(c.get('unit_price')) is not None and number(c['unit_price'])!=number(line['unit_price']):
                delta=(number(c['unit_price'])-number(line['unit_price']))*confirmed
                add(sku,'price_change','Unit price changed',f'{line["currency"]} {amount(line["unit_price"],2)} → {amount(c["unit_price"],2)} per unit; total variance {delta:.2f} for the confirmed quantity.',[line['unit_price'],c['unit_price'],str(confirmed)])
            if c.get('payment_terms')!=po['payment_terms']:
                add(sku,'payment_change','Payment terms changed',f'{po["payment_terms"]} → {c.get("payment_terms") or "Not provided"}.',[po['payment_terms'],c.get('payment_terms')])
        if 0<received<ordered: add(sku,'partial_receipt','Partial delivery received',f'{amount(received)} physically received; {amount(remaining)} still outstanding.',[str(received),str(remaining)])
        expected=c.get('delivery_date') or line['delivery_date']
        if remaining>0 and expected<state['as_of']:
            add(sku,'outstanding_delivery','Delivery outstanding after expected date',f'{amount(remaining)} units are still outstanding after {day(expected)}. A promise does not establish arrival.',[str(remaining),expected])
        late=[]
        for event in case['receipt_history']:
            for receipt in event['payload']['lines']:
                if receipt['sku']==sku and (event['effective_on']>line['delivery_date'] or event['effective_on']>receipt['expected_at_receipt']):
                    late.append({'receipt':event['id'],'on':event['effective_on'],'quantity':receipt['quantity'],'expected':receipt['expected_at_receipt'],'original':line['delivery_date']})
        if late:
            add(sku,'late_receipt','Goods arrived late',f'{len(late)} receipt(s) arrived after the original requested date or the promise known when recorded. Later promises do not change this history.',late)
        exposure=[r for r in coverage_for(case,sku) if Decimal(r['uncovered'])>0]
        if exposure:
            worst=max(exposure,key=lambda r:Decimal(r['uncovered']))
            add(sku,'customer_conflict','Possible customer delivery conflict',f'Recorded stock and outstanding confirmed supply leave a possible gap of {amount(worst["uncovered"])} units by {day(worst["due"])}. Allocation and arrival assumptions need checking.',exposure)
    return result

def sync_issues(state,order_id):
    detected={item['id']:item for item in detect_issues(state,order_id)}
    for issue_id,item in detected.items():
        old=state['issues'].get(issue_id)
        if old is None:
            state['issues'][issue_id]={**item,'detected':True,'status':'Open','owner':'','next_followup':None,'history':[{'on':state['as_of'],'event':'Issue detected','detail':item['detail']}]}
        else:
            fresh=not old['detected'] or old['fingerprint']!=item['fingerprint']
            if fresh:
                if old['status']=='Resolved': old['status']='Open'; action='Reopened after new evidence'
                else: action='Evidence updated'
                old['history'].append({'on':state['as_of'],'event':action,'detail':item['detail']})
            old.update(item); old['detected']=True
    for issue in state['issues'].values():
        if issue['order_id']==order_id and issue['id'] not in detected and issue['detected']:
            issue['detected']=False
            issue['history'].append({'on':state['as_of'],'event':'Discrepancy no longer detected','detail':'The latest records no longer show this condition. Review the resolution; previous actions remain recorded.'})

def set_support(state,order_id,kind,records):
    if kind not in SUPPORT_KINDS: raise ValueError('Unknown business information type.')
    if len(json.dumps(records))>24000: raise ValueError('Keep supporting information below 24,000 characters per category.')
    checked=parse_support(json.dumps(records),kind)
    po=state['orders'][order_id]; allowed={po['supplier_id']} if kind=='terms' else {x['sku'] for x in po['lines']}
    if not set(checked)<=allowed: raise ValueError('Supporting information must refer only to this order’s products or supplier.')
    state['support'][order_id][kind]=deepcopy(checked)
    append_event(state,order_id,'support_updated',state['as_of'],{'kind':kind,'records':checked})
    sync_issues(state,order_id)

def record_action(state,issue_id,status,owner,next_followup,note,draft='',*,action_type='',resolution_type='',approving_party='',decision='',reason='',related_ids=None):
    if status not in ISSUE_STATUSES: raise ValueError('Choose a valid issue status.')
    if not clean(note,2000): raise ValueError('Record a decision or next action so the history explains this change.')
    due=checked_date(next_followup,'follow-up date') if next_followup else None
    issue=state['issues'][issue_id]
    ids=list(dict.fromkeys(related_ids or [issue_id]))
    allowed=set(related_issue_ids(state,issue_id))
    if issue_id not in ids or not set(ids)<=allowed: raise ValueError('Actions must stay within this product’s related supply issues or the selected commercial issue.')
    if status=='Resolved':
        if resolution_type=='authorized_exception':
            if not all(clean(v) for v in (approving_party,decision,reason)): raise ValueError('Record the approving person or role, decision and reason for the exception.')
        elif resolution_type in ('','corrected'):
            if any(state['issues'][key]['detected'] for key in ids): raise ValueError('The discrepancy is still detected. Correct the records, or document an authorized exception decision.')
            resolution_type='corrected'
        else: raise ValueError('Choose correction or an authorized exception closure.')
    elif resolution_type: raise ValueError('A closure reason is only valid for a resolved issue.')
    payload={'issue_id':issue_id,'related_issue_ids':ids,'action_type':action_type or ('Resolved because corrected' if status=='Resolved' else 'Employee follow-up'),'resolution_type':resolution_type,'approving_party':clean(approving_party),'decision':clean(decision,2000),'reason':clean(reason,2000),'status':status,'owner':clean(owner,100),'next_followup':due,'note':clean(note,2000),'draft':clean(draft,7000),'message_sent':False,
        'remaining_discrepancies':[{'issue_id':key,'detail':state['issues'][key]['detail'],'fingerprint':state['issues'][key]['fingerprint']} for key in ids if state['issues'][key]['detected']],
        'reconciliation':make_case(state,issue['order_id'])['delivery_totals']}
    event_id=append_event(state,issue['order_id'],'followup_action',state['as_of'],payload)
    for key in ids:
        target=state['issues'][key]
        target.update(status=status,owner=payload['owner'],next_followup=due)
        target['history'].append({'on':state['as_of'],'event':'Employee action recorded','source':event_id,**deepcopy(payload)})
    return event_id

def save_investigation(state,issue_id,findings,trace,mode,context=''):
    issue=state['issues'][issue_id]; oid=issue['order_id']
    findings=deepcopy(findings)
    findings['reconciliation']=[t for t in make_case(state,oid)['delivery_totals'] if t['sku']==issue['sku']]
    investigation={'id':f'INV-{len(state["investigations"])+1:04d}','issue_id':issue_id,'related_issue_ids':related_issue_ids(state,issue_id),'reconciliation_version':1,'reconciliation':make_case(state,oid)['delivery_totals'],'order_id':oid,'on':state['as_of'],'mode':mode,'findings':deepcopy(findings),'trace':deepcopy(trace),'context':clean(context,2000),'evidence_sequence':len(state['events'])}
    state['investigations'].append(investigation)
    issue['history'].append({'on':state['as_of'],'event':'Investigation recorded','source':investigation['id'],'detail':mode})
    return investigation['id']

def order_status(state,order_id):
    case=make_case(state,order_id); po=case['po']; received=case['received_by_sku']
    if all(Decimal(received[x['sku']])>=Decimal(x['quantity']) for x in po['lines']): return 'Completed'
    if any(Decimal(v)>0 for v in received.values()): return 'Partially received'
    if any(i['order_id']==order_id and i['status']!='Resolved' and i['detected'] and i['kind']!='missing_confirmation' for i in state['issues'].values()): return 'Needs review'
    if any(x.get('quantity') is None for x in case['confirmation']['lines']): return 'Awaiting confirmation'
    return 'Confirmed'

def needs_followup(issue):
    return issue['status']!='Resolved' and (issue['detected'] or any(h['event'] in ('Employee action recorded','Investigation recorded') for h in issue['history']))

def requires_attention(state,issue):
    """Keep pending work separate from immutable historical delivery facts."""
    if not needs_followup(issue): return False
    if issue['kind'] in ('late_receipt','delivery_delay'):
        total=next(t for t in make_case(state,issue['order_id'])['delivery_totals'] if t['sku']==issue['sku'])
        if Decimal(total['outstanding_ordered'])==0:
            actions=[h for h in issue['history'] if h['event']=='Employee action recorded']
            return bool(actions and actions[-1].get('status')!='Resolved')
    return True

def order_rows(state):
    rows=[]
    for oid,po in state['orders'].items():
        case=make_case(state,oid); confirmed={x['sku']:x for x in case['confirmation']['lines']}
        for line in po['lines']:
            received=Decimal(case['received_by_sku'][line['sku']])
            rows.append({'Purchase order':oid,'Supplier':po['supplier'],'Product':line['sku'],'Ordered':amount(line['quantity']),'Latest confirmed':amount(confirmed[line['sku']].get('quantity')),'Physically received':amount(received),'Outstanding':amount(Decimal(line['quantity'])-received),'Requested delivery':day(line['delivery_date']),'Status':order_status(state,oid)})
    return rows

def prepared_investigation(state,issue_id):
    issue=state['issues'][issue_id]; case=make_case(state,issue['order_id']); sku=issue['sku']; po=case['po']; oid=po['order_id']
    related=[state['issues'][key] for key in related_issue_ids(state,issue_id)]
    active=[i for i in related if i['detected']]
    total=next(t for t in case['delivery_totals'] if t['sku']==sku)
    records=Records(case)
    records.call('get_purchase_order',{'order_id':oid})
    records.call('get_confirmation_history',{'order_id':oid})
    records.call('get_receipt_history',{'order_id':oid})
    implications=[]; missing=[]; steps=[]; coverage=[]
    commercial=issue['kind'] in ('price_change','payment_change')
    if commercial:
        terms=records.call('get_approved_terms',{'supplier_id':po['supplier_id']})
        if terms['status']!='available': missing.append('The approved supplier agreement is unavailable. The order comparison does not establish whether a separate revision was approved.')
        else:
            t=terms['record']; price=t.get('unit_prices',{}).get(sku)
            implications.append('Recorded agreed terms: '+(f'{t.get("currency") or "Currency unknown"} {amount(price,2)} per unit; ' if price is not None else '')+(t.get('payment_terms') or 'payment terms unavailable')+'.')
        rows=compare(po,case['confirmation']); row=next(x for x in rows if x['SKU']==sku)
        if row.get('total_variance') is not None: implications.append(f'Total price variance for the confirmed quantity: {next(x for x in po["lines"] if x["sku"]==sku)["currency"]} {Decimal(row["total_variance"]):,.2f}, excluding tax, freight and other charges.')
        steps.append('Ask the commercial owner to review the proposed change before agreeing to revised terms.')
        request='Please explain the proposed price or payment change and reconcile it with our purchase order and agreed terms.'
    else:
        inventory=records.call('get_inventory',{'sku':sku}); commitments=records.call('get_customer_commitments',{'sku':sku})
        coverage=coverage_for(case,sku)
        if coverage:
            worst=max(coverage,key=lambda r:Decimal(r['uncovered']))
            implications.append(f'By {day(worst["due"])}, cumulative commitments are {amount(worst["cumulative_committed"])} units and recorded usable stock plus outstanding confirmed arrivals cover {amount(worst["available_by_due"])}. The possible gap is {amount(worst["uncovered"])} units.')
            implications.append('Coverage assumes current unallocated stock remains free and future confirmed arrivals are on time. Goods already received are not added again. Other demand, receipts and handling time are excluded.')
        elif commitments['status']=='available' and not commitments['record']: implications.append('No customer commitments are recorded for this product; future demand remains uncertain.')
        else:
            inv=case.get('inventory',{}).get(sku,{})
            if not inv or inv.get('available') is None or not inv.get('as_of'):
                missing.append('Current usable stock and its snapshot date are missing. Customer delivery coverage cannot be established without them.')
            elif inv['as_of']>state['as_of']:
                missing.append('The stock snapshot is after the workspace date. Verify its date before assessing customer coverage.')
            elif any(e['effective_on']>inv['as_of'] or (e['effective_on']==inv['as_of'] and e['sequence']>case['inventory_recorded_sequence']) for e in case['receipt_history'] if any(x['sku']==sku for x in e['payload']['lines'])):
                missing.append('The stock snapshot predates a receipt, or a same-day receipt was recorded after it. Confirm a new usable-stock snapshot including those receipts; they are not added automatically. Customer coverage remains unknown.')
            if commitments['status']!='available': missing.append('Dated customer commitments are missing, so customer delivery impact cannot be established.')
            if total['latest_confirmed'] is None or not total['current_promised_date']: missing.append('A supplier quantity and arrival date are needed to assess remaining inbound supply.')
            if not missing: missing.append('Customer commitments predate the stock snapshot or the dates are not comparable. Verify outstanding demand and stock dates before assessing coverage.')
        if any(i['kind'] in ('delivery_delay','outstanding_delivery','customer_conflict') for i in active):
            alternatives=records.call('get_alternative_supply',{'sku':sku})
            if alternatives['status']!='available': missing.append('Alternative supply options are unavailable.')
            else:
                for option in alternatives['record']:
                    implications.append(f'{option.get("supplier") or "Alternative supplier"}: {amount(option.get("quantity"))} units, earliest {day(option.get("earliest_arrival"))}. {option.get("status") or "Availability not confirmed"}. This is an option to verify, not a supplier selection.')
        received=case['received_by_sku'][sku]; ordered=next(x for x in po['lines'] if x['sku']==sku)['quantity']
        implications.append(f'Physical delivery record: {amount(received)} of {amount(ordered)} ordered units received; {amount(Decimal(ordered)-Decimal(received))} still outstanding. Supplier confirmations are promises, not receipts.')
        implications.append(f'Original delivery date: {day(total["original_requested_date"])}; latest promised delivery: {day(total["current_promised_date"])}. Only the {amount(total["outstanding_confirmed"])} confirmed units not yet received can count as future inbound, subject to arrival timing.')
        if total['current_promised_date'] and total['current_promised_date']<state['as_of'] and number(total['outstanding_confirmed']): missing.append('The remaining supplier promise is overdue; actual arrival is unverified and is excluded from available inbound supply.')
        if number(total['unconfirmed_quantity']): missing.append(f'The supplier has not committed to {amount(total["unconfirmed_quantity"])} ordered units; availability and a firm delivery date remain unknown.')
        steps.append('Confirm the remaining delivery plan with the supplier and check any affected customer commitments with operations.')
        request='Please confirm the total quantity you can supply and a reliable delivery date for any outstanding units.'
        if issue['kind']=='late_receipt': request='Please clarify the reason for the late receipt and any action needed to prevent a repeat. The original requested date remains our comparison point.'
        if issue['kind']=='missing_confirmation': missing.append('No supplier confirmation is recorded for this product.')
    summary=issue['detail'] if commercial else reconciliation_sentence(total)
    if coverage and any(Decimal(r['uncovered'])>0 for r in coverage): summary+=' Recorded supply may leave customer deliveries uncovered; allocations and arrival timing need checking.'
    elif commercial: summary+=' An employee must review the commercial change before any acceptance.'
    else: summary+=' '+('The customer impact cannot yet be established.' if missing else 'Use the evidence below to decide the next follow-up.')
    if not active: summary='The reviewed discrepancy is no longer detected. Physical fulfilment is established only by receipt records. '+summary
    current_detail=issue['detail'] if commercial else reconciliation_sentence(total)
    draft=f'Subject: Follow-up on {oid} — {sku}\n\nDear {po["supplier"]},\n\nOur current position on {oid}: {current_detail}\n\n{request}\n\nThis message does not accept revised terms or authorize a purchase.\n\nKind regards,\nNorthstar Goods Procurement'
    return {'summary':summary,'changed':[current_detail]+[i['detail'] for i in active if i['detail']!=current_detail],'implications':implications,'missing':missing,'steps':steps,'draft':draft,'coverage':coverage,'trace':records.trace,'reconciliation':[total]}

def sample_workspace():
    from core import cases
    state=empty_workspace(); samples=cases()
    for oid,case in samples.items():
        create_order(state,case['po'],'2026-10-28')
        record_confirmation(state,oid,[{**x,'payment_terms':case['confirmation']['payment_terms']} for x in case['confirmation']['lines']],'2026-11-02',case['confirmation'].get('notes',''))
        support=deepcopy({k:case[k] for k in SUPPORT_KINDS})
        for stock in support['inventory'].values(): stock['as_of']=REFERENCE_DATE
        for kind,records in support.items(): set_support(state,oid,kind,records)
    for oid,supplier,sku,qty,price,due,status in [
        ('PO-1036','Meridian Ceramics (fictional)','MUG-350',100,'6.00','2026-11-04','complete'),
        ('PO-1039','Clearview Glass (fictional)','JAR-500',200,'4.50','2026-11-05','late'),
        ('PO-1051','Greenwood Tools (fictional)','BRUSH-01',300,'3.00','2026-11-08','partial'),
        ('PO-1060','Meridian Ceramics (fictional)','CUP-200',400,'5.00','2026-11-16','confirmed'),
        ('PO-1064','Woven Works (fictional)','MAT-01',250,'7.00','2026-11-18','awaiting'),
        ('PO-1071','Woven Works (fictional)','NAPKIN-01',500,'2.50','2026-11-22','confirmed'),
        ('PO-1102','Willow Studio (fictional)','BASKET-01',150,'11.00','2026-11-25','awaiting')]:
        po={'order_id':oid,'supplier':supplier,'supplier_id':'SUP-'+sku.split('-')[0],'payment_terms':'Net 30','lines':[{'sku':sku,'description':sku.replace('-',' ').title(),'quantity':qty,'unit_price':price,'currency':'EUR','delivery_date':due}]}
        create_order(state,po,'2026-10-28' if status!='awaiting' else '2026-11-09')
        if status!='awaiting': record_confirmation(state,oid,po['lines'],'2026-11-01','Delivery schedule confirmed.')
        if status=='complete':
            record_receipt(state,oid,[{'sku':sku,'quantity':'40'}],'2026-11-04')
            record_receipt(state,oid,[{'sku':sku,'quantity':'60'}],'2026-11-04')
        elif status=='late': record_receipt(state,oid,[{'sku':sku,'quantity':qty}],'2026-11-07','Delivery received two days after requested date.')
        elif status=='partial': record_receipt(state,oid,[{'sku':sku,'quantity':'100'}],'2026-11-08','First partial delivery received; balance pending.')
        for kind,records in {'inventory':{sku:{'available':str(qty if status in ('complete','late') else 100 if status=='partial' else 50),'as_of':REFERENCE_DATE}},'commitments':{sku:[]},'terms':{po['supplier_id']:{'unit_prices':{sku:price},'currency':'EUR','payment_terms':'Net 30'}},'alternatives':{sku:[]}}.items(): set_support(state,oid,kind,records)
    state['sample_orders']=list(state['orders'])
    shortfall='PO-1042|BOT-750|quantity_shortfall'
    record_action(state,shortfall,'Awaiting supplier','Lena Fischer','2026-11-11','Requested a firm delivery plan for the remaining 200 units. Sample action record only; SupplyOps did not send a message.')
    return state
