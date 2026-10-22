"""Focused SupplyOps acceptance workflows and preserved parsing/agent boundaries."""
from copy import deepcopy
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch,MagicMock
import io
import json
import tempfile
import unittest
from operations import (empty_workspace,sample_workspace,create_order,record_confirmation,record_receipt,
    received_quantities,current_confirmation,make_case,detect_issues,sync_issues,set_support,record_action,
    prepared_investigation,save_investigation,events_for,order_status,needs_followup)
from core import Records,compare,coverage_for,cases
from parsing import extract_text,parse

def order(oid='PO-TEST',sku='TEST-01',qty='100'):
    return {'order_id':oid,'supplier':'Example Manufacturing (fictional)','payment_terms':'Net 30','lines':[{'sku':sku,'description':'Example product','quantity':qty,'unit_price':'8.00','currency':'EUR','delivery_date':'2026-11-12'}]}

def fresh():
    state=empty_workspace(); create_order(state,order(),'2026-11-01'); return state

def confirm(state,qty='100',due='2026-11-12',price='8.00',received_on='2026-11-02'):
    return record_confirmation(state,'PO-TEST',[{'sku':'TEST-01','quantity':qty,'delivery_date':due,'unit_price':price}],received_on)

class OperatingWorkflows(unittest.TestCase):
    def test_a_normal_confirmation(self):
        state=fresh(); confirm(state)
        self.assertEqual(order_status(state,'PO-TEST'),'Confirmed')
        self.assertEqual(detect_issues(state,'PO-TEST'),[])
        self.assertFalse(any(needs_followup(i) for i in state['issues'].values()))
        self.assertEqual(received_quantities(state,'PO-TEST')['TEST-01'],'0')
        with self.assertRaises(ValueError): create_order(state,order(),'2026-11-01')
        with self.assertRaises(ValueError): create_order(state,order('PO-BAD',qty='-1'),'2026-11-01')

    def test_b_quantity_shortfall_and_revision_totals(self):
        state=fresh(); confirm(state,'80')
        issues=detect_issues(state,'PO-TEST')
        self.assertIn('quantity_shortfall',[i['kind'] for i in issues])
        issue_id=next(i['id'] for i in issues if i['kind']=='quantity_shortfall')
        result=prepared_investigation(state,issue_id)
        self.assertTrue(result['missing'])
        self.assertTrue(result['trace'])
        history=deepcopy(events_for(state,'PO-TEST','confirmation'))
        confirm(state,'100',received_on='2026-11-03')
        self.assertEqual(Decimal(current_confirmation(state,'PO-TEST')['lines'][0]['quantity']),100)
        self.assertEqual(events_for(state,'PO-TEST','confirmation')[0],history[0])
        self.assertFalse(state['issues'][issue_id]['detected'])

    def test_c_delivery_delay_keeps_original(self):
        state=fresh(); confirm(state,due='2026-11-26')
        self.assertEqual(state['orders']['PO-TEST']['lines'][0]['delivery_date'],'2026-11-12')
        self.assertEqual(compare(make_case(state,'PO-TEST')['po'],current_confirmation(state,'PO-TEST'))[0]['delay_days'],14)
        self.assertIn('delivery_delay',[i['kind'] for i in detect_issues(state,'PO-TEST')])

    def test_d_partial_receipts_accumulate_and_excess_rejected(self):
        state=fresh(); confirm(state)
        record_receipt(state,'PO-TEST',[{'sku':'TEST-01','quantity':'40'}],'2026-11-09')
        first=deepcopy(events_for(state,'PO-TEST','receipt')[0])
        self.assertEqual(order_status(state,'PO-TEST'),'Partially received')
        record_receipt(state,'PO-TEST',[{'sku':'TEST-01','quantity':'60'}],'2026-11-10')
        self.assertEqual(received_quantities(state,'PO-TEST')['TEST-01'],'100')
        self.assertEqual(order_status(state,'PO-TEST'),'Completed')
        self.assertEqual(events_for(state,'PO-TEST','receipt')[0],first)
        before=deepcopy(state)
        for row in [{'sku':'TEST-01','quantity':'1'},{'sku':'OTHER','quantity':'1'},{'sku':'TEST-01','quantity':'-2'}]:
            with self.assertRaises(ValueError): record_receipt(state,'PO-TEST',[row],'2026-11-10')
            self.assertEqual(state,before)
        with self.assertRaises(ValueError): confirm(state,'90',received_on='2026-11-10')

    def test_e_commercial_variance_exact(self):
        state=fresh(); confirm(state,price='8.80')
        record_confirmation(state,'PO-TEST',[{'sku':'TEST-01','quantity':'100','delivery_date':'2026-11-12','unit_price':'8.80','payment_terms':'50% advance'}],'2026-11-03')
        self.assertEqual({i['kind'] for i in detect_issues(state,'PO-TEST')},{'price_change','payment_change'})
        result=prepared_investigation(state,'PO-TEST|TEST-01|price_change')
        self.assertIn('80.00',' '.join(result['implications']))
        self.assertEqual(state['orders']['PO-TEST']['lines'][0]['unit_price'],'8')

    def test_f_followup_resolution_and_reopening(self):
        state=fresh(); confirm(state,'80'); iid='PO-TEST|TEST-01|quantity_shortfall'
        findings=prepared_investigation(state,iid)
        save_investigation(state,iid,findings,findings['trace'],'Evidence summary')
        record_action(state,iid,'Awaiting supplier','Lena','2026-11-11','Requested a firm balance date.','Reviewed draft')
        confirm(state,'100',received_on='2026-11-04')
        self.assertFalse(state['issues'][iid]['detected'])
        self.assertTrue(needs_followup(state['issues'][iid]))
        self.assertEqual(state['issues'][iid]['owner'],'Lena')
        record_action(state,iid,'Resolved','Lena',None,'Supplier has confirmed the full order; reviewed the revised promise.')
        original_investigation=deepcopy(state['investigations'][0])
        confirm(state,'70',received_on='2026-11-05')
        self.assertEqual(state['issues'][iid]['status'],'Open')
        self.assertTrue(any(h['event']=='Reopened after new evidence' for h in state['issues'][iid]['history']))
        self.assertEqual(state['investigations'][0],original_investigation)
        before=len(state['issues'][iid]['history']); sync_issues(state,'PO-TEST'); sync_issues(state,'PO-TEST')
        self.assertEqual(len(state['issues'][iid]['history']),before)

    def test_g_visitor_isolation_and_support_scope(self):
        first=sample_workspace(); second=sample_workspace()
        create_order(first,order(),'2026-11-10')
        self.assertNotIn('PO-TEST',second['orders'])
        self.assertEqual(first['support']['PO-TEST'],{})
        self.assertEqual(Records(make_case(first,'PO-TEST')).call('get_inventory',{'sku':'TEST-01'})['status'],'information unavailable')
        with self.assertRaises(ValueError): set_support(first,'PO-TEST','inventory',{'BOT-750':{'available':'100','as_of':'2026-11-10'}})
        self.assertEqual(second,sample_workspace())

    def test_late_receipt_cannot_be_reclassified_by_later_promise(self):
        state=empty_workspace(); po=order(); po['lines'][0]['delivery_date']='2026-11-05'
        create_order(state,po,'2026-11-01'); confirm(state,due='2026-11-05')
        record_receipt(state,'PO-TEST',[{'sku':'TEST-01','quantity':'100'}],'2026-11-07')
        original=deepcopy(events_for(state,'PO-TEST','receipt')[0])
        confirm(state,due='2026-11-09',received_on='2026-11-08')
        self.assertIn('late_receipt',[i['kind'] for i in detect_issues(state,'PO-TEST')])
        self.assertEqual(events_for(state,'PO-TEST','receipt')[0],original)
        self.assertEqual(original['payload']['lines'][0]['expected_at_receipt'],'2026-11-05')

    def test_multi_product_revisions_and_backdated_updates(self):
        state=empty_workspace(); po=order(); po['lines'].append({**po['lines'][0],'sku':'TEST-02'})
        create_order(state,po,'2026-11-01')
        confirm(state,'80',received_on='2026-11-03')
        record_confirmation(state,'PO-TEST',[{'sku':'TEST-02','quantity':'90','delivery_date':'2026-11-12'}],'2026-11-04')
        confirm(state,'50',received_on='2026-11-02')
        quantities={x['sku']:x['quantity'] for x in current_confirmation(state,'PO-TEST')['lines']}
        self.assertEqual(quantities,{'TEST-01':'80','TEST-02':'90'})

    def test_stock_coverage_does_not_count_received_units_twice(self):
        state=fresh(); confirm(state)
        record_receipt(state,'PO-TEST',[{'sku':'TEST-01','quantity':'40'}],'2026-11-09')
        set_support(state,'PO-TEST','inventory',{'TEST-01':{'available':'40','as_of':'2026-11-10'}})
        set_support(state,'PO-TEST','commitments',{'TEST-01':[{'customer':'Example Retail','quantity':'110','due':'2026-11-14'}]})
        coverage=coverage_for(make_case(state,'PO-TEST'),'TEST-01')[0]
        self.assertEqual(coverage['available_by_due'],'100')
        self.assertEqual(coverage['uncovered'],'10')
        set_support(state,'PO-TEST','inventory',{'TEST-01':{'available':'0','as_of':'2026-11-08'}})
        self.assertFalse(coverage_for(make_case(state,'PO-TEST'),'TEST-01'))

    def test_local_persistence_excludes_attachments(self):
        from storage import save_local,load_local
        state=fresh(); confirm(state)
        record_receipt(state,'PO-TEST',[{'sku':'TEST-01','quantity':'40'}],'2026-11-09',attachment={'filename':'receipt.txt','size':14,'data':b'not-persisted-document'})
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'workspace.json'; save_local(path,state)
            self.assertEqual(load_local(path),state)
            self.assertNotIn('not-persisted-document',path.read_text())
            path.write_text('broken')
            with self.assertRaises(ValueError): load_local(path)
            self.assertEqual(path.read_text(),'broken')

    def test_sample_environment_reconciles(self):
        state=sample_workspace()
        self.assertEqual(len(state['orders']),10)
        self.assertEqual({order_status(state,oid) for oid in state['orders']},{'Needs review','Completed','Partially received','Confirmed','Awaiting confirmation'})
        for oid,sku,kind,expected in [('PO-1042','BOT-750','quantity_shortfall','100'),('PO-1078','LUNCH-900','delivery_delay','430')]:
            result=prepared_investigation(state,f'{oid}|{sku}|{kind}')
            self.assertIn(expected,' '.join(result['implications']))
        self.assertIn('400.00',' '.join(prepared_investigation(state,'PO-1095|TOTE-01|price_change')['implications']))

class ParsingAndAgent(unittest.TestCase):
    def test_supported_readers_and_missing_fields(self):
        text='Order ID: PO-1\nSupplier: Fictional Supplier\nSKU | description | quantity | unit_price | currency | delivery_date\nABC | Bottle | 10 | 1.20 | EUR | 2026-11-12'
        self.assertEqual(parse(extract_text('x.txt',text.encode()))['lines'][0]['quantity'],'10')
        self.assertIsNone(parse('PO-1')['lines'][0]['quantity'])
        from docx import Document
        doc=Document(); doc.add_paragraph(text); buf=io.BytesIO(); doc.save(buf)
        self.assertIn('PO-1',extract_text('x.docx',buf.getvalue()))
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
        writer=PdfWriter(); page=writer.add_blank_page(width=600,height=800)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
        content=DecodedStreamObject(); content.set_data(b'BT /F1 12 Tf 50 750 Td (Order ID: PO-1) Tj ET'); page[NameObject('/Contents')]=writer._add_object(content)
        buf=io.BytesIO(); writer.write(buf); self.assertIn('PO-1',extract_text('x.pdf',buf.getvalue()))
        writer=PdfWriter(); writer.add_blank_page(width=100,height=100); buf=io.BytesIO(); writer.write(buf)
        with self.assertRaisesRegex(ValueError,'Scanned'): extract_text('scan.pdf',buf.getvalue())
        self.assertIn('PO-1',extract_text('supplier.eml',b'Subject: PO-1 confirmation\nContent-Type: text/plain; charset=utf-8\n\nWe confirm 100 units.'))

    def test_history_tools_are_scoped_and_read_only(self):
        state=fresh(); confirm(state); case=make_case(state,'PO-TEST'); records=Records(case)
        self.assertEqual(len(records.call('get_confirmation_history',{'order_id':'PO-TEST'})['record']),1)
        self.assertEqual(records.call('get_receipt_history',{'order_id':'PO-TEST'})['record'],[])
        for name,args in [('get_receipt_history',{'order_id':'PO-OTHER'}),('send_email',{}),('get_inventory',{'sku':'OTHER'}),('get_purchase_order',{'order_id':'PO-TEST','extra':1})]:
            with self.assertRaises(ValueError): records.call(name,args)

    def test_h_mocked_model_selection_and_call_boundaries(self):
        from agent import investigate,AgentFailure,client_for
        from google.genai import types
        state=fresh(); confirm(state,'80'); case=make_case(state,'PO-TEST'); client=Mock()
        call=NS(name='get_confirmation_history',args={'order_id':'PO-TEST'})
        response=NS(function_calls=[call],candidates=[NS(content=types.Content(role='model',parts=[types.Part.from_function_call(name=call.name,args=call.args)]))])
        findings={'summary':'80 of 100 units are confirmed. Customer impact is unknown.','changed':['20 units unconfirmed'],'implications':[],'missing':['Inventory and commitments unavailable'],'steps':['Request a balance date'],'draft':'Subject: PO-TEST\nPlease confirm the remaining 20 units.'}
        client.models.generate_content.side_effect=[response,NS(function_calls=[],text=json.dumps(findings))]
        activity=[]; result=investigate(case,'Quantities and delivery','',{},client,'test',activity.append)
        self.assertEqual([s['tool'] for s in result['trace']],['get_confirmation_history'])
        self.assertEqual(result['findings']['draft'],findings['draft']); self.assertEqual(len(activity),1)
        client.models.generate_content.side_effect=None; client.models.generate_content.return_value=response
        before=client.models.generate_content.call_count
        with self.assertRaises(AgentFailure): investigate(case,'Quantities and delivery','',{},client,'test')
        self.assertEqual(client.models.generate_content.call_count-before,4)
        with client_for('dummy-not-real') as configured: self.assertIsNotNone(configured)

class InlineUI:
    def start(self):
        from streamlit.testing.v1 import AppTest
        app=AppTest.from_file('app.py').run(timeout=30)
        self.assertFalse(app.exception)
        return app

    def click(self,app,label):
        next(x for x in app.button if x.label==label).click().run(timeout=30)
        self.assertFalse(app.exception)

    def pick_order(self,app,oid):
        table=next(x for x in app.dataframe if x.key and x.key.startswith('purchase-order-table-'))
        row=next(i for i,r in table.value.iterrows() if r['Purchase order']==oid)
        app.session_state[table.key]={'selection':{'rows':[int(row)],'columns':[],'cells':[]}}
        app.run(timeout=30)
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state['active_order'],oid)

    def open_update(self,app,receipt=False):
        self.click(app,'Record supplier response or delivery')
        next(x for x in app.radio if x.label=='What are you recording?').set_value('Goods physically received' if receipt else 'Supplier confirmation or revised promise').run()
        self.assertFalse(app.exception)

    def assess(self,app):
        self.click(app,'Review and resolve issue')
        self.click(app,'Assess the impact')

class UserInterface(InlineUI,unittest.TestCase):
    def test_connected_inline_followup_and_retained_draft(self):
        app=self.start(); self.assertFalse(app.segmented_control)
        self.assertNotIn('Change order',[x.label for x in app.selectbox])
        self.assess(app)
        self.assertEqual(app.session_state['active_order'],'PO-1042')
        self.assertEqual(len(app.session_state['supplyops']['investigations']),1)
        app.run(); self.assertEqual(len(app.session_state['supplyops']['investigations']),1)
        self.click(app,'Decide next action')
        next(x for x in app.text_area if x.label=='Supplier message').set_value('Reviewed supplier draft').run()
        next(x for x in app.text_area if x.label=='Internal note (optional)').set_value('Ask for a firm balance date.').run()
        next(x for x in app.text_input if x.label=='Responsible owner').set_value('Test owner').run()
        next(x for x in app.date_input if x.label=='Next follow-up date').set_value(date(2026,11,11)).run()
        self.click(app,'Back to review findings'); self.click(app,'Decide next action')
        self.assertEqual(next(x for x in app.text_area if x.label=='Supplier message').value,'Reviewed supplier draft')
        self.click(app,'Save action')
        self.assertIsNone(app.session_state['inline_panel'])
        event=events_for(app.session_state['supplyops'],'PO-1042','followup_action')[-1]['payload']
        self.assertEqual(event['draft'],'Reviewed supplier draft')
        self.assertEqual(event['status'],'Awaiting supplier'); self.assertFalse(event['message_sent'])
        self.assertTrue(any('Test owner' in x.value and 'Follow-up' in x.value for x in app.markdown))
        self.assertTrue(any(x.label=='Order activity' for x in app.expander))
        self.click(app,'Review and resolve issue'); app.run()
        self.assertEqual(len(app.session_state['supplyops']['investigations']),1)

    def test_create_matching_confirmation_stays_on_new_order(self):
        app=self.start(); app.radio(key='po_filter_picker').set_value('Completed').run()
        self.click(app,'Create purchase order')
        next(x for x in app.text_input if x.label=='Purchase order reference').set_value('PO-UI-01')
        next(x for x in app.text_input if x.label=='Supplier').set_value('UI Supplier')
        app.session_state['create-lines']={'edited_rows':{0:{'sku':'UI-01','description':'UI product','quantity':'50','unit_price':'2.50','currency':'EUR','delivery_date':'2026-11-20'}},'added_rows':[],'deleted_rows':[]}
        self.click(app,'Save purchase order')
        self.assertEqual(app.session_state['active_order'],'PO-UI-01')
        self.assertIsNone(app.session_state['inline_panel'])
        self.assertTrue(any('PO-UI-01 is outside this filter' in x.value for x in app.info))
        self.open_update(app); self.click(app,'Save supplier update')
        self.assertEqual(order_status(app.session_state['supplyops'],'PO-UI-01'),'Confirmed')
        self.assertEqual(received_quantities(app.session_state['supplyops'],'PO-UI-01')['UI-01'],'0')
        self.assertIsNone(app.session_state['inline_panel'])
        self.assertNotIn('Review and resolve issue',[x.label for x in app.button])
        self.click(app,'Show selected order')
        self.assertTrue(any('PO-UI-01 · Confirmed' in x.value for x in app.markdown))

    def test_table_selection_cells_filters_and_reruns(self):
        app=self.start(); original=deepcopy(app.session_state['supplyops'])
        self.pick_order(app,'PO-1078'); app.run()
        table=next(x for x in app.dataframe if x.key and x.key.startswith('purchase-order-table-'))
        previous=next(i for i,r in table.value.iterrows() if r['Purchase order']=='PO-1078')
        new=next(i for i,r in table.value.iterrows() if r['Purchase order']=='PO-1095')
        app.session_state[table.key]={'selection':{'rows':[int(previous)],'columns':[],'cells':[[int(new),'Supplier']]}}
        app.run(); self.assertEqual(app.session_state['active_order'],'PO-1095')
        app.radio(key='po_filter_picker').set_value('Completed').run()
        self.assertEqual(app.session_state['active_order'],'PO-1095')
        self.assertTrue(any('PO-1095 is outside this filter' in x.value for x in app.info))
        self.assertTrue(any('PO-1095 · Needs attention' in x.value for x in app.markdown))
        self.pick_order(app,'PO-1036')
        self.assertTrue(any('PO-1036 · Completed' in x.value for x in app.markdown))
        self.assertNotIn('Review and resolve issue',[x.label for x in app.button])
        self.assertEqual(app.session_state['supplyops'],original)

    def test_saved_confirmation_closes_form_and_marks_review_outdated(self):
        app=self.start(); self.assess(app); self.open_update(app)
        self.assertNotIn('Decide next action',[x.label for x in app.button])
        app.session_state['confirmation-lines-PO-1042-manual-False-0']={'edited_rows':{0:{'quantity':'750'}},'added_rows':[],'deleted_rows':[]}
        self.click(app,'Save supplier update')
        self.assertEqual(app.session_state['active_order'],'PO-1042')
        self.assertIsNone(app.session_state['inline_panel'])
        self.assertTrue(any('750 confirmed; 250 not yet confirmed' in x.value for x in app.success))
        self.click(app,'Review and resolve issue')
        self.assertTrue(any('outdated' in x.value for x in app.warning))
        self.assertTrue(next(x for x in app.button if x.label=='Decide next action').disabled)
        self.click(app,'Assess updated information')
        self.assertEqual(len(app.session_state['supplyops']['investigations']),2)
        self.assertEqual(app.session_state['supplyops']['investigations'][-1]['reconciliation'][0]['latest_confirmed'],'750')

    def test_failed_live_attempt_does_not_retry_on_rerun(self):
        from agent import AgentFailure
        with patch.dict('os.environ',{'ENABLE_LIVE_AI':'true','GEMINI_API_KEY':'test-key'}),patch('issue_workspace.client_for') as client,patch('issue_workspace.investigate',side_effect=AgentFailure('Unavailable',[])) as live:
            client.return_value.__enter__.return_value=Mock()
            app=self.start(); self.assess(app)
            self.assertEqual(live.call_count,1)
            self.assertTrue(any("couldn't complete" in x.value for x in app.error))
            app.run(); self.assertEqual(live.call_count,1)
            self.assertEqual(len(app.session_state['supplyops']['investigations']),0)
            self.click(app,'Review available records')
            self.assertEqual(len(app.session_state['supplyops']['investigations']),1)
            self.assertIn('incomplete live attempt',app.session_state['supplyops']['investigations'][0]['mode'])

    def test_empty_filter_retains_explicit_order_and_can_restore_list(self):
        from streamlit.testing.v1 import AppTest
        app=AppTest.from_file('app.py'); app.session_state['supplyops']=fresh(); app.run(timeout=30)
        app.radio(key='po_filter_picker').set_value('Completed').run()
        self.assertTrue(any('No orders match' in x.value for x in app.info))
        self.assertEqual(app.session_state['active_order'],'PO-TEST')
        self.assertTrue(any('PO-TEST · Awaiting confirmation' in x.value for x in app.markdown))
        self.click(app,'Show selected order')
        self.assertEqual(app.radio(key='po_filter_picker').value,'All orders')
        self.assertFalse(app.exception)

if __name__=='__main__': unittest.main()
