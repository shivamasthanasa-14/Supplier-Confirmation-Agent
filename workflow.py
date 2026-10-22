"""Business-facing views and verified, session-local workflow helpers."""
from copy import deepcopy
from datetime import date
from decimal import Decimal
import hashlib
import json
from core import compare, number
from parsing import validate, parse_support

FOCUSES = ['Check all discrepancies', 'Quantities and delivery', 'Pricing and commercial terms']
SUPPORT_LABELS = {'inventory': 'Available inventory', 'commitments': 'Customer commitments', 'terms': 'Agreed commercial terms', 'alternatives': 'Alternative supply options'}
SUPPORT_FIELDS = {
    'inventory': ['sku', 'available', 'as_of'],
    'commitments': ['sku', 'customer', 'quantity', 'due'],
    'terms': ['supplier_id', 'sku', 'unit_price', 'currency', 'payment_terms', 'valid_until'],
    'alternatives': ['sku', 'supplier', 'quantity', 'earliest_arrival', 'status'],
}
LABELS = {'sku': 'Product code', 'description': 'Product', 'quantity': 'Units', 'unit_price': 'Price per unit', 'currency': 'Currency', 'delivery_date': 'Delivery date', 'available': 'Available units', 'as_of': 'Stock checked on', 'customer': 'Customer / channel', 'due': 'Delivery commitment', 'supplier_id': 'Supplier reference', 'supplier': 'Supplier', 'payment_terms': 'Payment terms', 'valid_until': 'Valid until', 'earliest_arrival': 'Earliest arrival', 'status': 'Availability / conditions'}

def amount(value, decimals=None):
    n=number(value)
    if n is None: return 'Not provided'
    return f'{n:,.{decimals}f}' if decimals is not None else f'{n:,.6f}'.rstrip('0').rstrip('.')

def day(value):
    try: return date.fromisoformat(value).strftime('%d %b %Y').lstrip('0')
    except (TypeError, ValueError): return 'Not provided'

def document_rows(record):
    return [{'Product': x.get('description') or 'Not provided', 'Product code': x.get('sku') or 'Not provided', 'Units': amount(x.get('quantity')), 'Price per unit': f'{x.get("currency") or "?"} {amount(x.get("unit_price"),2)}', 'Delivery date': day(x.get('delivery_date'))} for x in record['lines']]

def change_rows(case):
    result=[]
    for row in compare(case['po'],case['confirmation']):
        sku=row['SKU']; p=next((x for x in case['po']['lines'] if x.get('sku')==sku),{}); c=next((x for x in case['confirmation']['lines'] if x.get('sku')==sku),{})
        if row.get('gap'):
            result.append({'Product':sku,'Detail':'Order line','Ordered':'See purchase order','Confirmed':row['gap']}); continue
        fields=[('quantity','Units',amount),('delivery_date','Delivery date',day),('unit_price','Price per unit',lambda v:amount(v,2)),('currency','Currency',lambda v:v or 'Not provided')]
        for key,label,fmt in fields:
            if p.get(key)!=c.get(key): result.append({'Product':sku,'Detail':label,'Ordered':fmt(p.get(key)),'Confirmed':fmt(c.get(key))})
    if case['po'].get('payment_terms')!=case['confirmation'].get('payment_terms'):
        result.append({'Product':'Whole order','Detail':'Payment terms','Ordered':case['po'].get('payment_terms') or 'Not provided','Confirmed':case['confirmation'].get('payment_terms') or 'Not provided'})
    return result

def discrepancy_sentences(case,focus=FOCUSES[0]):
    sentences=[]
    for row in compare(case['po'],case['confirmation']):
        sku=row['SKU']; p=next((x for x in case['po']['lines'] if x.get('sku')==sku),{}); c=next((x for x in case['confirmation']['lines'] if x.get('sku')==sku),{})
        if row.get('gap'): sentences.append(f'{sku}: the order lines need to be matched before comparison.'); continue
        diff=Decimal(row['quantity_difference']) if row['quantity_difference'] is not None else None
        if focus!=FOCUSES[2] and diff is not None and diff!=0:
            suffix=f'fewer units ({amount(row["shortfall_percent"])}% shortfall).' if diff<0 and row['shortfall_percent'] is not None else 'fewer units.' if diff<0 else 'extra units.'
            sentences.append(f'{sku}: {amount(c.get("quantity"))} of {amount(p.get("quantity"))} ordered units are confirmed — {amount(abs(diff))} '+suffix)
        if focus!=FOCUSES[2] and row['delay_days']:
            sentences.append(f'{sku}: delivery moves from {day(p.get("delivery_date"))} to {day(c.get("delivery_date"))} ({abs(row["delay_days"])} days '+('later).' if row['delay_days']>0 else 'earlier).'))
        price=Decimal(row['unit_price_difference']) if row['unit_price_difference'] is not None else None
        if focus!=FOCUSES[1] and price is not None and price!=0:
            total=row['total_variance']
            sentences.append(f'{sku}: the unit price changes from {p.get("currency")} {amount(p.get("unit_price"),2)} to {c.get("currency")} {amount(c.get("unit_price"),2)}'+(f', {c.get("currency")} {amount(abs(Decimal(total)),2)} '+('more' if Decimal(total)>0 else 'less')+' for the confirmed quantity.' if total is not None else '.'))
    if focus!=FOCUSES[1] and case['po'].get('payment_terms')!=case['confirmation'].get('payment_terms'):
        sentences.append(f'Payment terms change from {case["po"].get("payment_terms") or "not provided"} to {case["confirmation"].get("payment_terms") or "not provided"}.')
    return sentences or ['No comparable difference is identified in the selected fields. Missing details still need checking.']

def support_rows(records,kind):
    rows=[]
    for key,value in records.items():
        if kind=='inventory': rows.append({'sku':key,**{k:value.get(k) for k in ['available','as_of']}})
        elif kind in ('commitments','alternatives'):
            for row in value: rows.append({'sku':key,**{k:row.get(k) for k in SUPPORT_FIELDS[kind] if k!='sku'}})
        elif kind=='terms':
            prices=value.get('unit_prices',{})
            for sku,price in (prices or {None:None}).items(): rows.append({'supplier_id':key,'sku':sku,'unit_price':price,**{k:value.get(k) for k in ['currency','payment_terms','valid_until']}})
    return rows

def readable_support(records,kind):
    rows=support_rows(records,kind)
    return [{LABELS.get(k,k): (day(v) if k in ('as_of','due','valid_until','earliest_arrival') else amount(v) if k in ('available','quantity') else amount(v,2) if k=='unit_price' else v or 'Not provided') for k,v in row.items()} for row in rows]

def support_records(rows,kind):
    """Convert only explicitly entered cells; a blank table remains unavailable."""
    result={}
    for row in rows:
        row={k:(v.strip() if isinstance(v,str) else v) for k,v in row.items()}
        if not any(v not in (None,'') for v in row.values()): continue
        key=row.get('supplier_id') if kind=='terms' else row.get('sku')
        if not key: raise ValueError('Add a supplier reference.' if kind=='terms' else 'Add a product code for each row.')
        if kind=='inventory':
            if key in result: raise ValueError('Keep one stock record per product.')
            result[key]={'available':row.get('available'),'as_of':row.get('as_of')}
        elif kind in ('commitments','alternatives'):
            result.setdefault(key,[]).append({k:row.get(k) for k in SUPPORT_FIELDS[kind] if k!='sku'})
        else:
            term={k:row.get(k) or None for k in ['currency','payment_terms','valid_until']}
            if key in result and any(result[key].get(k)!=v for k,v in term.items()): raise ValueError('Use consistent terms for the same supplier.')
            result.setdefault(key,{**term,'unit_prices':{}})
            if row.get('sku') and row.get('unit_price') not in (None,''):
                if number(row['unit_price']) is None: raise ValueError('Enter a valid agreed unit price.')
                result[key]['unit_prices'][row['sku']]=str(number(row['unit_price']))
    return parse_support(json.dumps(result),kind)

def verified_case(records,support=None):
    checked=[validate(record) for record in records]
    for record in checked:
        if not record.get('order_id') or not (record.get('supplier') or record.get('supplier_id')) or not record['lines'] or not all(x.get('sku') for x in record['lines']):
            raise ValueError('Provide the order number, supplier name or reference, and product code for each line. Other unknown details can stay blank.')
        # Tool scoping can use the supplier name when the document has no internal reference.
        if not record.get('supplier_id'): record['supplier_id']=record['supplier']
    return {'po':checked[0],'confirmation':checked[1],**deepcopy(support or {})}

def signature(case,focus,context,use_live):
    return hashlib.sha256(json.dumps([case,focus,context,use_live],sort_keys=True).encode()).hexdigest()

def clarification_specs(case,focus):
    specs=[]
    for row in compare(case['po'],case['confirmation']):
        sku=row['SKU']
        operational=focus!=FOCUSES[2] and ((row.get('quantity_difference') is not None and Decimal(row['quantity_difference'])!=0) or (row.get('delay_days') or 0)>0)
        if operational:
            if sku not in case.get('inventory',{}): specs.append({'kind':'inventory','sku':sku,'question':f'How much usable stock is available for {sku}?'})
            if sku not in case.get('commitments',{}): specs.append({'kind':'commitments','sku':sku,'question':f'Which customer deliveries are committed for {sku}?'})
        commercial=focus!=FOCUSES[1] and ((row.get('unit_price_difference') is not None and Decimal(row['unit_price_difference'])!=0) or case['po'].get('payment_terms')!=case['confirmation'].get('payment_terms'))
        if commercial and case['po'].get('supplier_id') not in case.get('terms',{}): specs.append({'kind':'terms','sku':sku,'question':'Which pricing and payment terms have already been agreed with this supplier?'})
    unique=[]
    for spec in specs:
        identity=(spec['kind'],None if spec['kind']=='terms' else spec['sku'])
        if identity not in [(x['kind'],None if x['kind']=='terms' else x['sku']) for x in unique]: unique.append(spec)
    return unique[:2]

def apply_clarifications(case,answers):
    updated=deepcopy(case); notes=[]
    for answer in answers[:2]:
        spec=answer['spec']; kind=spec['kind']; rows=answer.get('rows',[])
        if kind=='commitments' and answer.get('no_commitments'):
            updated.setdefault(kind,{})[spec['sku']]=[]
            notes.append(f'User confirmed no customer commitments for {spec["sku"]}.'); continue
        if not any(any(v not in (None,'') for v in r.values() if v is not None) for r in rows):
            notes.append(spec['question']+' — skipped; information remains unavailable.'); continue
        # Each answer is scoped to the product/supplier that prompted the question.
        for row in rows:
            if kind=='terms': row={**row,'supplier_id':case['po']['supplier_id'],'sku':spec['sku']}
            else: row={**row,'sku':spec['sku']}
            parsed=support_records([row],kind)
            for key,value in parsed.items():
                if kind=='commitments': updated.setdefault(kind,{}).setdefault(key,[]).extend(value)
                else: updated.setdefault(kind,{})[key]=value
        notes.append(spec['question']+' — user-provided details included in this investigation.')
    updated['_clarification_notes']=notes
    return updated

def case_from_trace(case,trace):
    """A live summary may use only support actually retrieved by the model."""
    scoped={'po':deepcopy(case['po']),'confirmation':deepcopy(case['confirmation'])}
    mapping={'get_inventory':'inventory','get_customer_commitments':'commitments','get_approved_terms':'terms','get_alternative_supply':'alternatives'}
    for step in trace:
        if step['tool'] in mapping and step['evidence']['status']=='available':
            scoped.setdefault(mapping[step['tool']],{})[next(iter(step['arguments'].values()))]=deepcopy(step['evidence']['record'])
    return scoped
