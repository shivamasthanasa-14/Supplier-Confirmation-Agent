"""Business labels and derived display facts; never changes operational records."""
from datetime import date,timedelta
from decimal import Decimal
from operations import make_case,order_status,issue_groups,reconciliation_sentence
from core import number
from workflow import amount,day

def business_text(value):
    text=str(value or '')
    replacements={
        ' (fictional)':'','Fictional workspace':'Workspace',
        'Sample action record only; SupplyOps did not send a message.':'Supplier follow-up recorded; no message was sent by SupplyOps.',
        'still promised but not received':'confirmed units awaiting delivery',
        'not confirmed by the supplier':'not yet confirmed by the supplier',
        'physically received':'received','Physical delivery record:':'Goods received:',
        'cumulative commitments':'customer commitments to date',
        'recorded usable stock plus outstanding confirmed arrivals':'available stock and confirmed deliveries still due',
        'prototype storage limit':'workspace storage limit',
        'No record reads were executed.':'No records were checked during this attempt.',
        'information unavailable':'Information not available',
        'Internally escalated':'Escalated for review','Needs review':'Needs attention',
        'Record operational follow-up':'Assign follow-up','Escalate internally':'Escalate for review',
        'Resolve because corrected':'Resolved after correction','Close by authorized exception':'Closed with documented approval',
        'Employee action recorded':'Action saved','Investigation recorded':'Business impact reviewed',
        'Issue detected':'Issue identified','Evidence updated':'Order information updated',
        'Discrepancy no longer detected':'Issue no longer present',
        'Prepared example investigation':'Available-records review',
        'Evidence summary · custom records':'Available-records review',
        'Evidence summary after incomplete live attempt':'Available-records review after an incomplete AI review',
        'Live Gemini investigation':'Live AI review',
        'usable-stock snapshot':'usable stock figure','stock snapshot':'stock figure',
    }
    for old,new in replacements.items(): text=text.replace(old,new)
    return text

def status_label(value):
    return {'Needs review':'Needs attention','Open':'Open','Internally escalated':'Escalated for review'}.get(value,value)

def price_difference(value,currency):
    return currency+' '+f'{Decimal(value):,.2f}' if value is not None else 'Not provided'

def issue_title(issue):
    return {'quantity_shortfall':'Supplier quantity shortfall','quantity_excess':'Extra quantity proposed',
        'missing_confirmation':'Awaiting supplier confirmation','delivery_delay':'Delivery delayed',
        'price_change':'Unit price changed','payment_change':'Payment terms changed',
        'partial_receipt':'Partial delivery','outstanding_delivery':'Overdue delivery',
        'late_receipt':'Late delivery received','customer_conflict':'Potential customer delivery gap'}.get(issue['kind'],business_text(issue['title']))

def order_facts(state,oid):
    totals=make_case(state,oid)['delivery_totals']
    outstanding=any(number(t['outstanding_ordered'])>0 for t in totals)
    overdue=any(number(t['outstanding_ordered'])>0 and (t['current_promised_date'] or t['original_requested_date'])<state['as_of'] for t in totals)
    awaiting=any(t['latest_confirmed'] is None and number(t['outstanding_ordered'])>0 for t in totals)
    return {'open':outstanding,'attention':bool(issue_groups(state,oid)),'overdue':overdue,'awaiting':awaiting}

def overview_counts(state):
    facts=[order_facts(state,oid) for oid in state['orders']]
    return {key:sum(f[key] for f in facts) for key in ('open','attention','awaiting','overdue')}

def order_list(state):
    rows=[]
    for oid,po in state['orders'].items():
        case=make_case(state,oid); groups=issue_groups(state,oid)
        for total in case['delivery_totals']:
            line=next(x for x in po['lines'] if x['sku']==total['sku'])
            alerts=[issue_title(g) for g in groups if g['sku']==total['sku']]
            rows.append({'Purchase order':oid,'Supplier':business_text(po['supplier']),
                'Product':total['sku'],'Description':line.get('description') or total['sku'],
                'Delivery date':day(total['current_promised_date'] or total['original_requested_date']),
                'Status':status_label(order_status(state,oid)),'Needs attention':'; '.join(alerts) or 'No',
                'Outstanding':amount(total['outstanding_ordered'])})
    return rows

def quantity_summary(total):
    if number(total['outstanding_ordered'])==0:
        return f'All {amount(total["ordered"])} ordered units have been received.'+(' The latest supplier confirmation is '+amount(total['latest_confirmed'])+' units; the difference remains in the order records.' if total['latest_confirmed'] is not None and number(total['latest_confirmed'])!=number(total['ordered']) else '')
    if number(total['physically_received']):
        confirmed=total['outstanding_confirmed']
        if confirmed is not None:
            return f'{amount(total["physically_received"])} units have arrived. Another {amount(confirmed)} remain covered by the supplier’s current confirmation, while {amount(total["unconfirmed_quantity"])} are not yet confirmed.'
        return f'{amount(total["physically_received"])} units have arrived. {amount(total["outstanding_ordered"])} remain outstanding against the order; no supplier confirmation is recorded.'
    if total['latest_confirmed'] is None:
        return f'The supplier has not yet confirmed the {amount(total["ordered"])} units ordered. No goods have been recorded as received.'
    else:
        return f'The supplier has confirmed {amount(total["latest_confirmed"])} of the {amount(total["ordered"])} units ordered. No goods have been recorded as received; {amount(total["unconfirmed_quantity"])} units are not yet confirmed.'

def historical_delivery_note(state,oid,sku):
    case=make_case(state,oid)
    total=next(t for t in case['delivery_totals'] if t['sku']==sku)
    if number(total['outstanding_ordered'])>0: return ''
    dates=[e['effective_on'] for e in case['receipt_history'] if any(x['sku']==sku for x in e['payload']['lines'])]
    if not dates: return ''
    last=max(dates); delay=(date.fromisoformat(last)-date.fromisoformat(total['original_requested_date'])).days
    return ('Delivered '+str(delay)+(' day' if delay==1 else ' days')+' late · Received '+day(last)+'; originally requested '+day(total['original_requested_date'])) if delay>0 else ''

def supplier_draft(text,totals):
    for total in totals:
        position=quantity_summary(total)
        if total['current_promised_date']!=total['original_requested_date']:
            position+=' Delivery was requested for '+day(total['original_requested_date'])+' and is now expected on '+day(total['current_promised_date'])+'.'
        text=text.replace(reconciliation_sentence(total),position)
    return business_text(text)

def followup_signal(issue,as_of):
    due=issue.get('next_followup'); reference=date.fromisoformat(as_of)
    if due:
        when=date.fromisoformat(due)
        if when<reference: return 'Overdue follow-up'
        if when==reference: return 'Due today'
        if when<=reference+timedelta(days=3): return 'Due within 3 days'
    if not issue.get('owner'):
        new=not any(h['event']=='Employee action recorded' for h in issue.get('history',[]))
        return 'New · Unassigned' if new else 'Unassigned'
    if issue['status']=='Awaiting supplier': return 'Awaiting supplier'
    if issue['status']=='Internally escalated': return 'Escalated for review'
    return 'Open'
