"""SupplyOps: one order-centred procurement workspace."""
from copy import deepcopy
from datetime import date
from pathlib import Path
import hashlib
import os
import streamlit as st
from presentation import business_text,status_label,issue_title,overview_counts,order_facts,order_list,quantity_summary,historical_delivery_note
from operations import sample_workspace,create_order,set_support,make_case,events_for,order_status,issue_groups
from workflow import SUPPORT_LABELS,SUPPORT_FIELDS,support_rows,support_records,amount,day
from parsing import MAX_BYTES
from storage import load_local,save_local
from ui_helpers import edit_table,order_document,history_view,reconciliation_view

st.set_page_config(page_title='SupplyOps',page_icon='📦',layout='wide')
st.html('''<style>
.stMainBlockContainer{padding-top:2.2rem}h1{font-size:2.3rem!important}h2{font-size:1.6rem!important}
[data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]){display:grid;grid-template-columns:repeat(4,minmax(0,1fr))}
[data-testid="stHorizontalBlock"]:has([data-testid="stMetric"])>[data-testid="stColumn"]{width:100%!important;min-width:0!important}
[data-testid="stMetric"]{border:1px solid #dde5ed;border-radius:8px;padding:.65rem}
[data-testid="stMetricValue"]{font-size:1.6rem}
@media(max-width:640px){[data-testid="stHorizontalBlock"]:has([data-testid="stMetric"]){grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>''')

def setting(name,default=''):
    try: return os.environ.get(name) or st.secrets.get(name,default)
    except (FileNotFoundError,st.errors.StreamlitSecretNotFoundError): return os.environ.get(name,default)

api_key=setting('GEMINI_API_KEY')
live_enabled=str(setting('ENABLE_LIVE_AI','false')).lower()=='true' and bool(api_key)
model=setting('GEMINI_MODEL','gemini-flash-latest')
local_mode=str(setting('SUPPLYOPS_LOCAL_PERSISTENCE','false')).lower()=='true'
local_path=Path('.local/workspace.json')
if 'supplyops' not in st.session_state:
    try: st.session_state['supplyops']=load_local(local_path) if local_mode else sample_workspace()
    except ValueError as exc: st.error(business_text(exc)); st.stop()
state=st.session_state['supplyops']
st.session_state.setdefault('evidence_files',{})
draft_values=st.session_state.setdefault('update_draft_values',{})
for draft_key in list(st.session_state):
    if draft_key.startswith(('update-note-','update-date-','receipt-note-','receipt-date-')):
        draft_values[draft_key]=st.session_state[draft_key]
for draft_key,draft_value in draft_values.items():
    if draft_key.startswith(('update-note-','update-date-','receipt-note-','receipt-date-')) and draft_key not in st.session_state: st.session_state[draft_key]=draft_value

def commit(function,*args,**kwargs):
    updated=deepcopy(st.session_state['supplyops'])
    result=function(updated,*args,**kwargs)
    if local_mode: save_local(local_path,updated)
    st.session_state['supplyops']=updated
    return result

def go(destination,order_id=None,issue_id=None,update_type=None):
    """Open or close an inline order action; no page navigation is involved."""
    oid=order_id or st.session_state['active_order']
    st.session_state['active_order']=oid
    if issue_id:
        st.session_state.pop('order_notice',None)
        from issue_workspace import open_issue
        open_issue(issue_id,'po')
        st.session_state['inline_panel']={'order_id':oid,'kind':'issue'}
    elif destination=='Supplier Updates':
        st.session_state.pop('order_notice',None)
        st.session_state['inline_panel']={'order_id':oid,'kind':'update'}
        if update_type:
            st.session_state.setdefault('update_choices',{})[oid]=update_type
            st.session_state['update-type-'+oid]=update_type
    else: st.session_state['inline_panel']=None
    st.session_state['creating_order']=False
    st.rerun()

def attach(file,text=None):
    if not file: return None
    data=file.getvalue()
    if not data or len(data)>MAX_BYTES: raise ValueError('Choose a non-empty attachment up to 5 MB.')
    return {'filename':Path(file.name).name,'size':len(data),'data':data,'text':text}

def mark_saved(event_id,kind,file_data):
    for upload_key in ('confirm-file-'+selected_order+'-'+str(generation),'receipt-file-'+selected_order+'-'+str(generation)):
        st.session_state.get('pending_uploads',{}).pop(upload_key,None)
    if file_data: st.session_state['evidence_files'][event_id]=file_data
    latest=make_case(st.session_state['supplyops'],selected_order)
    event=next(e for e in st.session_state['supplyops']['events'] if e['id']==event_id)
    touched={line['sku'] for line in event['payload']['lines']}
    changes=[]
    for total in latest['delivery_totals']:
        if total['sku'] not in touched: continue
        if kind=='confirmation':
            changes.append(total['sku']+': '+amount(total['latest_confirmed'])+' confirmed; '+amount(total['unconfirmed_quantity'])+' not yet confirmed.')
        else:
            changes.append(total['sku']+': '+amount(total['physically_received'])+' received in total; '+amount(total['outstanding_confirmed'])+' confirmed units awaiting delivery; '+amount(total['unconfirmed_quantity'])+' not yet confirmed.')
    st.session_state['order_notice']={'order_id':selected_order,'message':('Supplier update saved. ' if kind=='confirmation' else 'Delivery saved. ')+' '.join(changes)}
    st.session_state['inline_panel']=None
    st.session_state.pop('confirmation_preview',None)
    st.session_state.setdefault('order_form_generations',{})[selected_order]=generation+1
    st.rerun()

if st.session_state.pop('clear_po_search',False):
    st.session_state['po-search']=''; st.session_state['po_search_saved']=''
if '_next_po_filter' in st.session_state:
    st.session_state['po_filter']=st.session_state.pop('_next_po_filter')
    st.session_state['po_filter_picker']=st.session_state['po_filter']
if st.session_state.get('active_order') not in state['orders']:
    st.session_state['active_order']=st.session_state.get('order_pick') if st.session_state.get('order_pick') in state['orders'] else next(iter(state['orders']))

def remember_filter():
    st.session_state['po_filter']=st.session_state['po_filter_picker']

def remember_search():
    st.session_state['po_search_saved']=st.session_state['po-search']

st.title('SupplyOps')
st.write('Manage supplier confirmations, deliveries and the follow-ups that keep orders moving.')
with st.expander('Workspace information'):
    st.write('Sample workspace with illustrative procurement records.')
    st.caption('Northstar Goods · Business date '+day(state['as_of']))
    st.write('Records are saved on this computer. Attachments are available for this visit only.' if local_mode else 'Changes and attachments are available for this visit only and are separate from other visitors.')
    st.caption('No messages, purchase orders or approvals are sent automatically. Use non-confidential documents in this shared demonstration.')
selected_order=st.session_state['active_order']
po=state['orders'][selected_order]
current_case=make_case(state,selected_order)
generation=st.session_state.setdefault('order_form_generations',{}).get(selected_order,0)
if st.session_state.get('flash'):
    st.success(st.session_state.pop('flash'))

def order_actions():
    pending=issue_groups(state,selected_order)
    panel=st.session_state.get('inline_panel')
    is_open=bool(panel and panel['order_id']==selected_order)
    cols=st.columns(2 if pending else 1)
    if cols[0].button('Record supplier response or delivery',type='primary' if not pending and not is_open else 'secondary'):
        go('Supplier Updates',selected_order)
    if pending:
        if cols[1].button('Review and resolve issue',type='primary' if not is_open else 'secondary'):
            remembered=st.session_state.get('issue_route',{}).get('id')
            chosen=next((group['id'] for group in pending if remembered in group['related_ids']),pending[0]['id'])
            go('Issues',selected_order,issue_id=chosen)

st.subheader('Purchase Orders')
counts=overview_counts(state)
for col,label,field in zip(st.columns(4),['Open purchase orders','Orders needing attention','Awaiting confirmation','Overdue deliveries'],['open','attention','awaiting','overdue']): col.metric(label,counts[field])
if st.session_state.get('creating_order'):
    st.markdown('#### Record a purchase order')
    st.caption('This records a purchasing commitment in SupplyOps. It does not issue or send an order to a supplier.')
    with st.form('create-po'):
        a,b=st.columns(2)
        reference=a.text_input('Purchase order reference',max_chars=60)
        supplier=b.text_input('Supplier',max_chars=200)
        terms=a.text_input('Agreed payment terms',value='Net 30',max_chars=200)
        created=b.date_input('Order recorded on',value=date.fromisoformat(state['as_of']),max_value=date.fromisoformat(state['as_of']))
        rows=edit_table([{'sku':None,'description':None,'quantity':None,'unit_price':None,'currency':'EUR','delivery_date':None}],['sku','description','quantity','unit_price','currency','delivery_date'],'create-lines')
        st.caption('Use one row per product. Dates: YYYY-MM-DD. Add rows for a multi-product order.')
        save=st.form_submit_button('Save purchase order',type='primary')
    if save:
        try:
            lines=[r for r in rows if any(r.get(k) not in (None,'') for k in ['sku','description','quantity','unit_price','delivery_date'])]
            oid=commit(create_order,{'order_id':reference,'supplier':supplier,'payment_terms':terms,'lines':lines},created.isoformat())
            st.session_state['flash']='Purchase order recorded. Nothing has been sent to the supplier.'
            go('Purchase Orders',oid)
        except (ValueError,OSError) as exc: st.error(business_text(exc))
    if st.button('Back to purchase orders'): st.session_state['creating_order']=False; st.rerun()
else:
    if st.button('Create purchase order'): st.session_state['creating_order']=True; st.rerun()
    st.session_state.setdefault('po_filter_picker',st.session_state.get('po_filter','All orders'))
    status_filter=st.radio('Show',['All orders','Awaiting confirmation','Needs review','Partially received','Completed'],format_func=status_label,horizontal=True,key='po_filter_picker',on_change=remember_filter)
    st.session_state.setdefault('po-search',st.session_state.get('po_search_saved',''))
    search=st.text_input('Search orders',placeholder='Order reference, supplier or product',key='po-search',on_change=remember_search).strip().casefold()
    rows=order_list(state)
    rows=[row for row in rows if not search or any(search in str(row[field]).casefold() for field in ['Purchase order','Supplier','Product','Description'])]
    filtered=[r for r in rows if status_filter=='All orders' or (status_filter=='Needs review' and order_facts(state,r['Purchase order'])['attention']) or (status_filter!='Needs review' and r['Status']==status_label(status_filter))]
    if filtered:
        st.caption('Select an order number or row to open its details below.')
        identities=[(r['Purchase order'],r['Product']) for r in filtered]
        table_token=hashlib.sha256(repr((status_filter,search,identities,selected_order)).encode()).hexdigest()[:16]
        table_key='purchase-order-table-'+table_token
        default_row=next((i for i,r in enumerate(filtered) if r['Purchase order']==selected_order),None)
        selection=st.dataframe([{k:v for k,v in row.items() if k!='Description'} for row in filtered],hide_index=True,width='stretch',height=min(280,38+35*len(filtered)),row_height=35,key=table_key,on_select='rerun',selection_mode=['single-row','single-cell'],selection_default={'selection':{'rows':[default_row] if default_row is not None else []}})
        picked=list(selection.selection.rows)
        cells=[list(cell) for cell in selection.selection.cells]
        previous=st.session_state.get('_po_table_event',{})
        cell_changed=cells and (previous.get('key')!=table_key or cells!=previous.get('cells'))
        selected_index=cells[-1][0] if cell_changed else picked[0] if picked else None
        st.session_state['_po_table_event']={'key':table_key,'rows':picked,'cells':cells}
        if selected_index is not None and 0<=selected_index<len(filtered):
            chosen_order=filtered[selected_index]['Purchase order']
            if chosen_order!=selected_order:
                st.session_state['active_order']=chosen_order
                st.session_state['inline_panel']=None
                st.session_state.pop('order_notice',None)
                # Recreate the table with the matching row highlight and panel.
                st.rerun()
    else: st.info('No orders match these filters. Change the status or search to find an order.')
    selected_visible=any(r['Purchase order']==selected_order for r in filtered)
    if not selected_visible:
        st.info(selected_order+' is outside this filter. Its details remain selected below; choose another row or show this order in the list.')
        if st.button('Show selected order'):
            st.session_state['_next_po_filter']='All orders'; st.session_state['clear_po_search']=True; st.rerun()
    if selected_order in state['orders']:
        with st.container(border=True):
            st.markdown('#### '+selected_order+' · '+status_label(order_status(state,selected_order)))
            st.write('**Supplier:** '+business_text(po['supplier']))
            totals=current_case['delivery_totals']
            notice=st.session_state.get('order_notice')
            if notice and notice['order_id']==selected_order:
                st.success(notice['message'])
            for total in totals:
                st.write('**'+total['sku']+'** · '+quantity_summary(total))
                historical=historical_delivery_note(state,selected_order,total['sku'])
                if historical: st.caption(historical)
            reconciliation_view(totals)
            pending=issue_groups(state,selected_order)
            st.caption('Needs attention: '+('Yes' if pending else 'No'))
            if pending:
                st.markdown('##### Needs attention')
                for item in pending: st.write(issue_title(item)+' · '+status_label(item['status'])+' · '+(item['owner'] or 'Unassigned')+(' · Follow-up '+day(item['next_followup']) if item['next_followup'] else ''))
            order_actions()
            panel=st.session_state.get('inline_panel')
            if panel and panel['order_id']==selected_order:
                with st.container(border=True):
                    if panel['kind']=='update':
                        from supplier_updates import render_update
                        render_update(state,selected_order,commit,attach,mark_saved,live_enabled,api_key,model,generation)
                        if st.button('Close entry form'): go('Purchase Orders',selected_order)
                    else:
                        from issue_workspace import render
                        render(state,commit,go,live_enabled,api_key,model)
            with st.expander('Order activity'):
                history_view(events_for(state,selected_order),st.session_state['evidence_files'],key='po-history-'+selected_order)
    with st.expander('Original purchase order'): order_document(po)
    with st.expander('Stock, customer commitments and supplier terms'):
        st.caption('Keep usable stock and customer delivery commitments up to date. Recording goods received does not change the stock figure automatically.')
        kind=st.selectbox('Information to review',list(SUPPORT_LABELS),format_func=lambda k:SUPPORT_LABELS[k],key='support-kind')
        existing=state['support'].get(selected_order,{}).get(kind,{})
        fields=[f for f in SUPPORT_FIELDS[kind] if f!='supplier_id']
        rows=support_rows(existing,kind)
        if kind=='terms': rows=[{k:v for k,v in r.items() if k!='supplier_id'} for r in rows]
        with st.form('business-context-'+selected_order+'-'+kind):
            edited=edit_table(rows,fields,'context-'+selected_order+'-'+kind+'-'+str(len(state['events'])))
            no_commitments=st.checkbox('No customer commitments recorded for these products') if kind=='commitments' else False
            st.caption('Use product codes from this order and dates in YYYY-MM-DD format. A blank table means information is unavailable.')
            save_context=st.form_submit_button('Save business information')
        if save_context:
            try:
                if no_commitments: records={x['sku']:[] for x in po['lines']}
                else:
                    populated=[r for r in edited if any(v not in (None,'') for v in r.values())]
                    if kind=='terms': populated=[{**r,'supplier_id':po['supplier_id']} for r in populated]
                    records=support_records(populated,kind)
                commit(set_support,selected_order,kind,records)
                st.session_state['flash']='Business information updated for this order.'; st.rerun()
            except (ValueError,TypeError,KeyError,OSError) as exc: st.error(business_text(exc) if isinstance(exc,(ValueError,OSError)) else 'Check the quantities, product codes and dates.')

