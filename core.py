"""Session-scoped evidence, exact calculations, and prepared investigations."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from datetime import date
import json

REPORT_DATE = '2026-11-02'
FIELDS = ['sku', 'description', 'quantity', 'unit_price', 'currency', 'delivery_date']

def cases():
    result = {}
    for oid, title, sku, qty, price, due, cq, cp, cd, terms, stock, commitments in [
        ('PO-1042','Quantity shortfall','BOT-750',1000,'12.50','2026-11-12',800,'12.50','2026-11-12','Net 30',150,[('DTC replenishment',450,'2026-11-14'),('Haven Retail',600,'2026-11-18')]),
        ('PO-1078','Delivery delay','LUNCH-900',600,'18.00','2026-11-12',600,'18.00','2026-11-26','Net 30',120,[('Elm Stores',350,'2026-11-16'),('DTC replenishment',200,'2026-11-23')]),
        ('PO-1095','Commercial terms','TOTE-01',500,'8.00','2026-11-20',500,'8.80','2026-11-20','50% advance, balance before dispatch',200,[])]:
        supplier = 'SUP-NORD'
        line = dict(sku=sku,description={'BOT-750':'750 ml insulated bottle','LUNCH-900':'900 ml lunch box','TOTE-01':'Canvas market tote'}[sku],quantity=qty,unit_price=price,currency='EUR',delivery_date=due)
        po = dict(order_id=oid,supplier_id=supplier,supplier='Nordlicht Manufacturing (fictional)',payment_terms='Net 30',lines=[line])
        confirmation = deepcopy(po)
        confirmation['lines'][0].update(quantity=cq,unit_price=cp,delivery_date=cd)
        confirmation['payment_terms']=terms
        confirmation['notes']='The balance of 200 units is pending production allocation; we cannot yet confirm a dispatch date.' if oid=='PO-1042' else ('Production scheduling has moved arrival to 26 November. Please acknowledge receipt.' if oid=='PO-1078' else 'Our revised price and advance-payment schedule apply to this confirmation. Please advise your acceptance.')
        result[oid] = dict(title=title,po=po,confirmation=confirmation,inventory={sku:{'available':stock,'as_of':REPORT_DATE,'note':'Unallocated usable stock; no other inbound receipts recorded.'}},commitments={sku:[dict(customer=c,quantity=q,due=d) for c,q,d in commitments]},terms={supplier:{'unit_prices':{sku:price},'currency':'EUR','payment_terms':'Net 30','valid_until':'2026-12-31'}},alternatives={sku:([{'supplier':'Baltic Components (fictional)','quantity':250,'earliest_arrival':'2026-11-13','status':'Indicative availability; no reservation or approved purchase'}] if oid=='PO-1078' else [])})
    return result

class Records:
    def __init__(self, case):
        self.case=deepcopy(case)
        self.trace=[]
    def call(self, name, args):
        spec={'get_purchase_order':('order_id','po'),'get_confirmation_history':('order_id','confirmation_history'),'get_receipt_history':('order_id','receipt_history'),'get_inventory':('sku','inventory'),'get_customer_commitments':('sku','commitments'),'get_approved_terms':('supplier_id','terms'),'get_alternative_supply':('sku','alternatives')}
        if name not in spec: raise ValueError('Unknown read-only tool')
        field,bucket=spec[name]
        if not isinstance(args,dict) or set(args)!={field} or not isinstance(args[field],str) or len(args[field])>80: raise ValueError('Invalid tool arguments')
        allowed = {self.case['po'].get('order_id')} if field=='order_id' else ({self.case['po'].get('supplier_id')} if field=='supplier_id' else {x.get('sku') for x in self.case['po']['lines']})
        if field=='sku' and self.case.get('issue_context',{}).get('sku'): allowed={self.case['issue_context']['sku']}
        if args[field] not in allowed: raise ValueError('Reference outside current investigation')
        value=self.case.get(bucket) if field=='order_id' else self.case.get(bucket,{}).get(args[field])
        response={'status':'information unavailable'} if value is None else {'status':'available','record':value}
        if value is not None and len(json.dumps(value))>24000: response={'status':'information unavailable','reason':'Record exceeds the AI input-size limit; review its full history in the workspace.'}
        if bucket=='receipt_history' and self.case.get('delivery_totals'): response['python_delivery_totals']=self.case['delivery_totals']
        response['source']=self.case['po'].get('order_id')+' / '+bucket+' / '+args[field]
        if field=='sku' and bucket in ('inventory','commitments'):
            seen={step['tool'] for step in self.trace if step['arguments'].get('sku')==args[field]}|{name}
            if {'get_inventory','get_customer_commitments'}<=seen:
                response['python_coverage']=coverage_for(self.case,args[field])
                response['assumptions']='Unallocated stock and confirmed arrival remain available. No other demand, receipts, or handling lead time included.'
        self.trace.append({'tool':name,'arguments':args,'evidence':deepcopy(response)})
        return response

def number(value):
    if value is None or value=='': return None
    try:
        n=Decimal(str(value))
        return n if n.is_finite() and 0<=n<=Decimal('1000000000000') and n.as_tuple().exponent>=-6 else None
    except InvalidOperation: return None

def coverage_for(case,sku):
    po,c=case['po'],case['confirmation']
    if po.get('order_id')!=c.get('order_id') or po.get('supplier_id')!=c.get('supplier_id'): return []
    inv=case.get('inventory',{}).get(sku,{})
    commitments=case.get('commitments',{}).get(sku)
    lines=[x for x in c['lines'] if x.get('sku')==sku]
    if commitments is None or len(lines)!=1 or number(inv.get('available')) is None: return []
    line=lines[0]; incoming=number(line.get('quantity')); arrival=line.get('delivery_date')
    if incoming is None or not arrival or not inv.get('as_of'): return []
    if 'received_by_sku' in case:
        # The current stock snapshot already includes usable physical receipts.
        incoming=max(Decimal(0),incoming-Decimal(case['received_by_sku'].get(sku,'0')))
        reference=case.get('reference_date',inv['as_of'])
        if inv['as_of']>reference: return []
        if any(e['effective_on']>inv['as_of'] or
               (e['effective_on']==inv['as_of'] and e['sequence']>case.get('inventory_recorded_sequence',float('inf')))
               for e in case.get('receipt_history',[]) if any(x['sku']==sku for x in e['payload']['lines'])): return []
        # An overdue promise is not proof of available stock.
        if arrival<reference: incoming=Decimal(0)
    cumulative=Decimal(0); rows=[]
    for item in sorted(commitments,key=lambda x:x['due']):
        if item['due']<inv['as_of']: return []
        cumulative+=Decimal(str(item['quantity']))
        supply=number(inv['available'])+(incoming if arrival<=item['due'] else 0)
        rows.append({'sku':sku,'due':item['due'],'cumulative_committed':str(cumulative),'available_by_due':str(supply),'uncovered':str(max(Decimal(0),cumulative-supply))})
    return rows

def clarification_questions(case,focus):
    from workflow import clarification_specs
    return [spec['question'] for spec in clarification_specs(case,focus)]

def prepared(case,focus='Check all discrepancies',answers=None):
    """Evidence-derived example/comparison; never a claimed model execution."""
    from workflow import amount, day, discrepancy_sentences
    records=Records(case); po=case['po']; c=case['confirmation']
    records.call('get_purchase_order',{'order_id':po['order_id']})
    rows=compare(po,c); implications=[]; missing=[]; steps=[]; requests=[]; coverage=[]
    matched=po.get('order_id')==c.get('order_id') and po.get('supplier_id')==c.get('supplier_id')
    if not matched:
        missing.append('The order number or supplier differs between the documents. Match the right documents before relying on this comparison.')
        steps.append('Resolve the document references before considering any changes.')
    for r in rows:
        sku=r['SKU']; line=next((x for x in c['lines'] if x.get('sku')==sku),{})
        if r.get('gap'): missing.append(f'{sku}: an order line is missing or cannot be matched.'); continue
        labels={'quantity_difference':'quantity','delay_days':'delivery date','unit_price_difference':'price or currency'}
        for key,label in labels.items():
            if r.get(key) is None: missing.append(f'{sku}: the {label} comparison is incomplete. Check the source documents or fill in the missing details.')
        diff=Decimal(r['quantity_difference']) if r['quantity_difference'] is not None else None
        price=Decimal(r['unit_price_difference']) if r['unit_price_difference'] is not None else None
        operational=focus!='Pricing and commercial terms' and ((diff is not None and diff!=0) or (r['delay_days'] or 0)>0)
        if operational and matched:
            inv=records.call('get_inventory',{'sku':sku}); comm=records.call('get_customer_commitments',{'sku':sku})
            product_coverage=coverage_for(case,sku); coverage.extend(product_coverage)
            if product_coverage:
                for row in product_coverage:
                    gap=Decimal(row['uncovered'])
                    if gap>0:
                        implications.append(f'{sku}: by {day(row["due"])}, customer commitments total {amount(row["cumulative_committed"])} units, while recorded supply covers {amount(row["available_by_due"])}. This leaves a possible gap of {amount(gap)} units.')
                    else:
                        implications.append(f'{sku}: recorded supply covers the {amount(row["cumulative_committed"])} units committed by {day(row["due"])}.')
                implications.append('Coverage assumes the available stock stays free and the confirmed delivery arrives on time. Other demand, receipts and warehouse handling time are not included.')
            elif comm['status']=='available' and not comm['record']:
                implications.append(f'{sku}: no customer commitments are recorded. This does not establish future demand.')
            else:
                missing.append(f'{sku}: delivery coverage cannot be established without usable dated stock, dated customer commitments and confirmed arrival details.')
            if diff is not None and diff<0:
                missing.append(f'{sku}: the delivery plan for the {amount(abs(diff))} unconfirmed units needs checking against the supplier notes.')
                requests.append(f'Please confirm availability and a reliable arrival date for the remaining {amount(abs(diff))} units of {sku}.')
            if (r['delay_days'] or 0)>0:
                alt=records.call('get_alternative_supply',{'sku':sku})
                if alt['status']!='available': missing.append(f'{sku}: alternative supply availability is not recorded.')
                elif not alt['record']: implications.append(f'{sku}: no alternative supply options are recorded.')
                else:
                    for option in alt['record']:
                        implications.append(f'{sku}: {option.get("supplier") or "An alternative supplier"} lists {amount(option.get("quantity"))} units with earliest arrival {day(option.get("earliest_arrival"))}. {option.get("status") or "Availability is unconfirmed"}. This is an option to verify, not an approved replacement.')
                requests.append(f'Please explain the {r["delay_days"]}-day delay for {sku} and confirm whether a partial or earlier delivery is possible.')
            steps.append('Check stock allocation and customer delivery dates with operations, then agree which commitments need attention.')
        commercial=focus!='Quantities and delivery' and ((price is not None and price!=0) or po.get('payment_terms')!=c.get('payment_terms'))
        if commercial and matched:
            terms=records.call('get_approved_terms',{'supplier_id':po.get('supplier_id')})
            if r['total_variance'] is not None:
                total=Decimal(r['total_variance'])
                implications.append(f'The confirmed quantity would cost {line.get("currency")} {amount(abs(total),2)} '+('more' if total>0 else 'less' if total<0 else 'in price variance')+' than at the purchase-order unit price. This comparison excludes tax, freight and any other charges.')
            if terms['status']=='available':
                t=terms['record']; agreed=t.get('unit_prices',{}).get(sku)
                details=[]
                if agreed is not None: details.append(f'{t.get("currency") or "Currency not recorded"} {amount(agreed,2)} per unit')
                if t.get('payment_terms'): details.append(t['payment_terms'])
                if details: implications.append('Recorded agreed terms: '+', '.join(details)+'.')
                else: missing.append('The agreed-terms record does not include the relevant price or payment terms.')
            else: missing.append('The agreed commercial terms are unavailable; the purchase order alone does not establish whether a separate revision was approved.')
            requests.append(f'Please reconcile the price and payment terms for {sku} with our purchase order and confirm the basis for any proposed change.')
            steps.append('Ask the commercial owner to review the proposed price and payment changes before replying with a decision.')
    for doc in (po,c):
        if not doc.get('payment_terms'): missing.append('Payment terms are missing from one of the documents.')
    if not matched: requests=['Please confirm the correct order and supplier references; our documents do not match.']
    summary_parts=discrepancy_sentences(case,focus)
    if not matched:
        summary='The order or supplier references do not match. The displayed differences are provisional until the documents are reconciled.'
    else:
        first=summary_parts[0]
        exposed=[r for r in coverage if Decimal(r['uncovered'])>0]
        if exposed:
            worst=max(exposed,key=lambda x:Decimal(x['uncovered']))
            second=f'Recorded stock and confirmed arrivals leave a possible gap of {amount(worst["uncovered"])} units for {worst["sku"]} by {day(worst["due"])}; confirm allocations and arrival timing before treating this as a missed delivery.'
        elif any(Decimal(r['total_variance'])!=0 for r in rows if r.get('total_variance') is not None) and focus!='Quantities and delivery':
            second='Check the revised commercial terms with the responsible owner before agreeing to any change.'
        elif missing: second='The available information is incomplete, so any effect on customer deliveries still needs checking.'
        else: second='Use the findings below to confirm the right supplier follow-up.'
        summary=first+' '+second
    context_notes=list(case.get('_clarification_notes',[]))
    if answers:
        context_notes.extend(f'{q}: {a}' for q,a in answers.items() if a)
    draft=f'Subject: Clarification requested — {po.get("order_id")}\n\nDear {po.get("supplier") or "Supplier"},\n\nThank you for your confirmation. '+(' '.join(dict.fromkeys(requests)) or 'Please confirm any missing order details and the delivery schedule.')+'\n\nWe are reviewing these points internally. This message does not accept revised terms or authorize a purchase.\n\nKind regards,\nNorthstar Goods Procurement'
    return dict(summary=summary,changed=summary_parts,changes=rows,coverage=coverage,implications=list(dict.fromkeys(implications)),missing=list(dict.fromkeys(missing)),steps=list(dict.fromkeys(steps)) or ['Review the comparison and confirm any missing details with the supplier.'],draft=draft,trace=records.trace,context_notes=context_notes)

def compare(po, confirmation):
    rows=[]
    for p in po['lines']:
        matches=[c for c in confirmation['lines'] if c.get('sku') and c.get('sku')==p.get('sku')]
        r={'SKU':p.get('sku'),'ordered':p.get('quantity'),'confirmed':None,'quantity_difference':None,'shortfall_percent':None,'delay_days':None,'unit_price_difference':None,'total_variance':None}
        if len(matches)!=1:
            r['gap']='Missing or ambiguous matching confirmation line'; rows.append(r); continue
        c=matches[0]; r['confirmed']=c.get('quantity')
        a,b=number(p.get('quantity')),number(c.get('quantity'))
        if a is not None and b is not None:
            r['quantity_difference']=str(b-a)
            r['shortfall_percent']=str(max(Decimal(0),(a-b)/a*100).quantize(Decimal('.01'))) if a else None
        try: r['delay_days']=(date.fromisoformat(c['delivery_date'])-date.fromisoformat(p['delivery_date'])).days
        except (ValueError,TypeError,KeyError): pass
        x,y=number(p.get('unit_price')),number(c.get('unit_price'))
        if x is not None and y is not None and p.get('currency') and p.get('currency')==c.get('currency'):
            r['unit_price_difference']=str(y-x)
            if b is not None: r['total_variance']=str((y-x)*b)
        rows.append(r)
    for c in confirmation['lines']:
        if c.get('sku') not in {p.get('sku') for p in po['lines']}: rows.append({'SKU':c.get('sku'),'gap':'Unmatched supplier line; verify before calculating'})
    return rows


