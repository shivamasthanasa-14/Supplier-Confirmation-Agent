"""Existing supplier-confirmation and goods-receipt forms, rendered inline."""
from datetime import date
import hashlib
import streamlit as st
from operations import make_case,record_confirmation,record_receipt
from presentation import business_text
from parsing import extract_text,parse
from agent import client_for,extract_with_gemini
from ui_helpers import edit_table,pending_file,order_document

def render_update(state,selected_order,commit,attach,mark_saved,live_enabled,api_key,model,generation):
    po=state['orders'][selected_order]
    current_case=make_case(state,selected_order)
    st.markdown('##### Record supplier response or delivery')
    st.session_state.setdefault('update-type-'+selected_order,st.session_state.get('update_choices',{}).get(selected_order,'Supplier confirmation or revised promise'))
    update_type=st.radio('What are you recording?',['Supplier confirmation or revised promise','Goods physically received'],format_func=lambda value:'Update supplier confirmation' if value=='Supplier confirmation or revised promise' else 'Record goods received',key='update-type-'+selected_order)
    st.session_state.setdefault('update_choices',{})[selected_order]=update_type
    if update_type=='Supplier confirmation or revised promise':
        st.caption('Enter the total quantity the supplier currently confirms, including units already delivered. This replaces the earlier confirmation.')
        file=pending_file('Upload supplier document (optional)',['pdf','docx','txt','eml'],'confirm-file-'+selected_order+'-'+str(generation))
        token=hashlib.sha256(file.getvalue()).hexdigest() if file else 'manual'
        preview=st.session_state.get('confirmation_preview',{})
        preview=preview if preview.get('order_id')==selected_order and preview.get('token')==token else {}
        if file and st.button('Read document'):
            try:
                text=extract_text(file.name,file.getvalue()); extracted=parse(text)
                if live_enabled and any(not x.get('sku') or x.get('quantity') is None or not x.get('delivery_date') for x in extracted['lines']):
                    if st.session_state.get('extract_count',0)>=4: raise ValueError('The assisted-reading allowance is used. Enter and review the details manually.')
                    st.session_state['extract_count']=st.session_state.get('extract_count',0)+1
                    with client_for(api_key) as client: extracted=extract_with_gemini(text,client,model)
                if extracted.get('order_id') and extracted['order_id']!=selected_order: raise ValueError('This attachment refers to another purchase order. Select the matching order or choose the correct attachment.')
                if extracted.get('supplier_id') and extracted['supplier_id']!=po['supplier_id']: raise ValueError('The supplier reference does not match this order. Check the attachment before saving.')
                st.session_state['confirmation_preview']={'order_id':selected_order,'token':token,'original':extracted,'text':text}; st.rerun()
            except Exception as exc:
                st.error(business_text(exc) if isinstance(exc,(ValueError,UnicodeError)) else 'The attachment could not be read. You can enter the supplier details manually.')
        if preview:
            initial=[{**x,'payment_terms':preview['original'].get('payment_terms')} for x in preview['original']['lines']]
            st.info('Document read. Review and correct the details below, then save the update. Nothing has been saved yet.')
            if any(not row.get('sku') or row.get('quantity') is None or not row.get('delivery_date') for row in initial):
                st.caption('Some details could not be identified. Complete the product code, quantity and delivery date before saving.')
            with st.expander('View document and extracted details'):
                st.text(preview['text']); order_document({**preview['original'],'order_id':preview['original'].get('order_id') or selected_order,'supplier':preview['original'].get('supplier') or 'Not provided'})
        else:
            latest={x['sku']:x for x in current_case['confirmation']['lines']}
            initial=[{**x,**({k:v for k,v in latest[x['sku']].items() if v is not None} if latest[x['sku']].get('quantity') is not None else {}),'payment_terms':latest[x['sku']].get('payment_terms') or po['payment_terms']} for x in po['lines']]
            st.caption('Recorded values are shown below. Change them to match the latest supplier update before saving.')
        with st.container():
            update_date=st.date_input('Supplier update date',key='update-date-'+selected_order+'-'+str(generation),value=date.fromisoformat(state['as_of']),max_value=date.fromisoformat(state['as_of']))
            edited=edit_table(initial,['sku','quantity','delivery_date','unit_price','payment_terms','notes'],'confirmation-lines-'+selected_order+'-'+token+'-'+str(bool(preview))+'-'+str(generation),labels={'quantity':'Confirmed total quantity','delivery_date':'Expected delivery date','unit_price':'Confirmed unit price'})
            notes=st.text_area('Supplier notes (optional)',key='update-note-'+selected_order+'-'+token+'-'+str(generation),value=preview.get('original',{}).get('notes') or '',max_chars=2000)
            st.caption('Delivery dates: YYYY-MM-DD. Prices use the order currency. Saving an update does not approve a price or terms change.')
            save_confirmation=st.button('Save supplier update',type='primary')
        if save_confirmation:
            try:
                if preview:
                    source_currency={r.get('sku'):r.get('currency') for r in preview['original']['lines']}
                    for row in edited:
                        if source_currency.get(row.get('sku')): row['currency']=source_currency[row['sku']]
                file_data=attach(file,preview.get('text'))
                event_id=commit(record_confirmation,selected_order,[r for r in edited if any(v not in (None,'') for v in r.values())],update_date.isoformat(),notes,file_data)
                mark_saved(event_id,'confirmation',file_data)
            except (ValueError,TypeError,KeyError,OSError) as exc: st.error(business_text(exc) if isinstance(exc,(ValueError,OSError)) else 'Check the quantities, dates and product references.')
    else:
        st.caption('Enter only the quantities received in this delivery. They will be added to earlier receipts; the supplier confirmation stays unchanged.')
        with st.container():
            receipt_date=st.date_input('Receipt date',key='receipt-date-'+selected_order+'-'+str(generation),value=date.fromisoformat(state['as_of']),max_value=date.fromisoformat(state['as_of']))
            rows=edit_table([{'sku':line['sku'],'quantity':None} for line in po['lines']],['sku','quantity'],'receipt-lines-'+selected_order+'-'+str(generation),disabled=['sku'],fixed=True)
            note=st.text_area('Receipt note (optional)',key='receipt-note-'+selected_order+'-'+str(generation),max_chars=2000)
            file=pending_file('Receipt document (optional)',['pdf','docx','txt'],'receipt-file-'+selected_order+'-'+str(generation))
            save_receipt=st.button('Save goods received',type='primary')
        if save_receipt:
            try:
                file_data=attach(file)
                entered=[r for r in rows if r.get('quantity') not in (None,'')]
                if not entered: raise ValueError('Enter a received quantity for at least one product.')
                event_id=commit(record_receipt,selected_order,entered,receipt_date.isoformat(),note,file_data)
                mark_saved(event_id,'receipt',file_data)
            except (ValueError,TypeError,KeyError,OSError) as exc: st.error(business_text(exc) if isinstance(exc,(ValueError,OSError)) else 'Check the received quantities and product codes.')
