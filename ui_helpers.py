"""Small reusable Streamlit views; no shared visitor state."""
import streamlit as st
from presentation import business_text,status_label,quantity_summary
from decimal import Decimal
from workflow import LABELS,document_rows,readable_support,amount,day

FIELD_LABELS={**LABELS,'payment_terms':'Payment terms','notes':'Supplier notes','quantity':'Quantity','expected_at_receipt':'Expected when received','original_requested_date':'Original requested date'}
TOOL_LABELS={'get_purchase_order':'Original purchase order','get_confirmation_history':'Supplier confirmation history','get_receipt_history':'Physical goods receipt history','get_inventory':'Available stock','get_customer_commitments':'Customer delivery commitments','get_approved_terms':'Approved commercial terms','get_alternative_supply':'Recorded alternative supply'}

def pending_file(label,types,key):
    """Keep an unsaved attachment across navigation without setting widget state."""
    uploads=st.session_state.setdefault('pending_uploads',{})
    def changed():
        chosen=st.session_state.get(key)
        if chosen is None: uploads.pop(key,None)
        else: uploads[key]=chosen
    selected=st.file_uploader(label,type=types,key=key,on_change=changed)
    if selected: uploads[key]=selected
    retained=selected or uploads.get(key)
    if retained and not selected:
        st.caption('Attached document: '+retained.name)
        if st.button('Remove document',key=key+'-remove'):
            uploads.pop(key,None); st.rerun()
    return retained

def edit_table(rows,fields,key,disabled=None,fixed=False,labels=None):
    preserve=key.startswith(('confirmation-lines-','receipt-lines-'))
    if preserve:
        saved=st.session_state.setdefault('table_drafts',{})
        bases=st.session_state.setdefault('table_draft_bases',{})
        if key not in st.session_state: bases[key]=saved.get(key,rows)
        rows=bases.setdefault(key,rows)
    rows=[{field:None if row.get(field) in (None,'') else business_text(row[field]) if field=='supplier' else str(row[field]) for field in fields} for row in rows] or [{f:None for f in fields}]
    edited=st.data_editor(rows,hide_index=True,num_rows='fixed' if fixed else 'dynamic',key=key,width='stretch',disabled=disabled or [],column_config={f:st.column_config.TextColumn((labels or {}).get(f,FIELD_LABELS.get(f,f.replace('_',' ').capitalize()))) for f in fields})
    if preserve: saved[key]=edited
    return edited

def order_document(po):
    st.write(f'**{po["order_id"]} · {business_text(po["supplier"])}**')
    st.dataframe(document_rows(po),hide_index=True,width='stretch')
    st.write('Agreed payment terms: '+(po.get('payment_terms') or 'Not provided'))

def history_rows(events):
    labels={'order_created':'Purchase order recorded','confirmation':'Supplier total commitment','receipt':'Goods physically received','support_updated':'Business information updated','followup_action':'Employee follow-up'}
    rows=[]
    for event in sorted(events,key=lambda e:(e['effective_on'],e['sequence'])):
        p=event['payload']; lines=p.get('lines',[])
        details='; '.join(f'{x["sku"]}: {amount(x["quantity"])} units'+(' · expected '+day(x.get('delivery_date')) if event['kind']=='confirmation' else '') for x in lines)
        rows.append({'Date':day(event['effective_on']),'Update':labels.get(event['kind'],event['kind']),'Details':details or p.get('note') or p.get('kind') or 'Original order recorded','Source':event['id']})
    return rows

def activity_entries(events):
    """Chronological business timeline; original events are never rewritten."""
    entries=[]; promises={}; receipts={}
    for event in sorted(events,key=lambda e:(e['effective_on'],e['sequence'])):
        p=event['payload']; kind=event['kind']; details=[]
        if kind=='order_created':
            title='Purchase order recorded'
            details=[f'{x["sku"]}: {amount(x["quantity"])} units ordered, requested {day(x["delivery_date"])}.' for x in p['order']['lines']]
            details.append('Supplier: '+p['order']['supplier']+'. Recorded in SupplyOps; not sent automatically.')
        elif kind=='confirmation':
            title='Supplier revised confirmation' if any(x['sku'] in promises for x in p['lines']) else 'Supplier confirmed'
            for line in p['lines']:
                sku=line['sku']; previous=promises.get(sku)
                text=f'{sku}: total commitment {amount(line["quantity"])} units; promised delivery {day(line["delivery_date"])}.'
                if previous:
                    text+=f' Previously {amount(previous["quantity"])} units, promised {day(previous["delivery_date"])}. This replaces the previous total.'
                    if line.get('unit_price')!=previous.get('unit_price'): text+=f' Unit price changed from {amount(previous.get("unit_price"),2)} to {amount(line.get("unit_price"),2)} {line.get("currency") or ""}.'
                    if line.get('payment_terms')!=previous.get('payment_terms'): text+=' Payment terms: '+(line.get('payment_terms') or 'Not provided')+'.'
                else: text+=f' Unit price {amount(line.get("unit_price"),2)} {line.get("currency") or ""}; payment terms {line.get("payment_terms") or "not provided"}.'
                details.append(text); promises[sku]=line
            if p.get('notes'): details.append('Supplier message: '+p['notes'])
        elif kind=='receipt':
            title='Additional goods received' if any(receipts.get(x['sku']) for x in p['lines']) else 'Goods received'
            for line in p['lines']:
                sku=line['sku']; receipts[sku]=receipts.get(sku,Decimal(0))+Decimal(line['quantity'])
                details.append(f'{sku}: {amount(line["quantity"])} units received; cumulative receipts {amount(receipts[sku])}. Expected when received: {day(line.get("expected_at_receipt"))}. The supplier promise is unchanged.')
            if p.get('note'): details.append(p['note'])
        elif kind=='followup_action':
            title=p.get('action_type') or {'Awaiting supplier':'Supplier clarification requested','Internally escalated':'Issue escalated internally','Resolved':'Issue resolved by employee'}.get(p['status'],'Operational follow-up recorded')
            if p.get('resolution_type')=='authorized_exception': title='Exception closed through a recorded authorized decision'
            elif p.get('resolution_type')=='corrected': title='Discrepancy resolved because corrected'
            details=[p.get('note') or '', 'Recorded status: '+p['status']+'.']
            if p.get('owner'): details.append('Responsible owner: '+p['owner']+'.')
            if p.get('next_followup'): details.append('Next follow-up: '+day(p['next_followup'])+'.')
            if p.get('approving_party'): details.append('Approving role/person recorded by employee: '+p['approving_party']+'. Decision: '+p['decision']+'. Reason: '+p['reason']+'. SupplyOps records this decision; it does not grant approval.')
            for alert in p.get('remaining_discrepancies',[]): details.append('Discrepancy retained: '+alert['detail'])
            if p['status']=='Resolved': details.append('Closure does not establish full physical receipt of the order.')
            if p.get('draft'): details.append('Supplier draft recorded; no message was sent automatically.')
        else:
            title='Business information updated'
            details=[{'inventory':'Usable-stock snapshot','commitments':'Customer delivery commitments','terms':'Approved commercial terms','alternatives':'Alternative supply information'}.get(p.get('kind'),'Supporting information')+' updated for this order.']
        entries.append({'date':event['effective_on'],'title':title,'details':details,'source':event['id']})
    return entries

def history_view(events,attachments=None,key='history'):
    if not events: st.write('No updates recorded.'); return
    for entry in activity_entries(events):
        st.markdown('**'+day(entry['date'])+' · '+business_text(entry['title'])+'**')
        for detail in entry['details']:
            if detail: st.write(business_text(detail))
    with st.expander('View an original history entry'):
        selected=st.selectbox('Source entry',[e['id'] for e in events],key=key)
        e=next(e for e in events if e['id']==selected); payload=e['payload']
        st.write(day(e['effective_on'])+' · '+e['kind'].replace('_',' ').capitalize())
        if payload.get('order'): order_document(payload['order'])
        if payload.get('lines'):
            st.dataframe([{FIELD_LABELS.get(k,k.replace('_',' ').capitalize()):str(v) if v is not None else 'Not provided' for k,v in row.items()} for row in payload['lines']],hide_index=True,width='stretch')
        if payload.get('records'):
            st.dataframe(readable_support(payload['records'],payload['kind']),hide_index=True,width='stretch')
        for field in ['notes','note','owner','next_followup','status','approving_party','decision','reason']:
            if payload.get(field): st.write(field.replace('_',' ').capitalize()+': '+business_text(payload[field]))
        if payload.get('draft'): st.text(business_text(payload['draft'])); st.caption('Recorded draft only; SupplyOps did not send it.')
        attached=(attachments or {}).get(selected)
        if attached:
            st.download_button('Download attached evidence',attached['data'],file_name=attached['filename'],key=key+'-download-'+selected)
            if attached.get('text'): st.text(attached['text'])
        elif payload.get('attachment'): st.caption('Attachment metadata is retained; the document itself is available only during the original visitor session.')

def coverage_view(rows):
    st.dataframe([{'Product':r['sku'],'By':day(r['due']),'Committed units':amount(r['cumulative_committed']),'Recorded available supply':amount(r['available_by_due']),'Possible gap':amount(r['uncovered'])} for r in rows],hide_index=True,width='stretch')

def trace_view(trace,key):
    for index,step in enumerate(trace,1):
        name=step['tool']; evidence=step['evidence']; ref=next(iter(step['arguments'].values()))
        st.markdown(f'**{index}. {TOOL_LABELS.get(name,name)} · {ref}**')
        st.caption('Source: '+evidence.get('source',ref))
        if evidence['status']!='available': st.write(business_text(evidence.get('reason','Information is not available for this order.'))); continue
        if name=='get_purchase_order': order_document(evidence['record'])
        elif name in ('get_confirmation_history','get_receipt_history'):
            rows=history_rows(evidence['record'])
            if rows: st.dataframe(rows,hide_index=True,width='stretch')
            else: st.write('No entries recorded.')
        else:
            kind={'get_inventory':'inventory','get_customer_commitments':'commitments','get_approved_terms':'terms','get_alternative_supply':'alternatives'}[name]
            rows=[{k:business_text(v) for k,v in row.items()} for row in readable_support({ref:evidence['record']},kind)]
            if rows: st.dataframe(rows,hide_index=True,width='stretch')
            else: st.write('No entries recorded.')
        if evidence.get('python_coverage'): coverage_view(evidence['python_coverage'])
    if not trace: st.write('No records were checked during this attempt.')

def findings_view(findings):
    st.markdown('#### Key finding')
    summary=business_text(findings['summary'])
    if findings.get('reconciliation') and 'latest supplier total' in summary:
        summary=' '.join(quantity_summary(total) for total in findings['reconciliation'])
    with st.container(border=True): st.write(summary)
    for title,field in [('Business impact','implications'),('Information to confirm','missing'),('Recommended action','steps')]:
        items=list(dict.fromkeys(findings.get(field) or []))
        if items:
            st.markdown('#### '+title)
            for item in items: st.write('• '+business_text(item))

def findings_evidence_view(findings):
    if findings.get('reconciliation'):
        st.caption('Order and delivery position when this review was completed')
        reconciliation_view(findings['reconciliation'])
    for item in dict.fromkeys(findings.get('changed') or []): st.write(business_text(item))
    if findings.get('coverage'): coverage_view(findings['coverage'])


def reconciliation_view(totals):
    st.dataframe([{'Product':t['sku'],'Ordered':amount(t['ordered']),'Latest confirmed total':amount(t['latest_confirmed']),
        'Goods received':amount(t['physically_received']),'Confirmed awaiting delivery':amount(t['outstanding_confirmed']),
        'Quantity not yet confirmed':amount(t.get('unconfirmed_quantity')),'Remaining order quantity':amount(t['outstanding_ordered']),
        'Original delivery date':day(t['original_requested_date']),'Expected delivery date':day(t['current_promised_date'])} for t in totals],hide_index=True,width='stretch')
    for total in totals:
        if Decimal(total.get('received_above_confirmed') or '0')>0:
            st.caption(total['sku']+': receipts exceed the latest supplier commitment. The unconfirmed quantity compares the promise with the order; total outstanding compares physical receipts with the order. Reconcile the supplier promise before treating these balances as additive.')
