"""Order-centred business journeys and meaningful attention requirements."""
from copy import deepcopy
from datetime import date
from io import BytesIO
import unittest
from streamlit.testing.v1 import AppTest
from operations import (sample_workspace,make_case,record_receipt,record_confirmation,record_action,
    issue_groups,events_for,order_status,empty_workspace,create_order,prepared_investigation,
    save_investigation,requires_attention)
from presentation import overview_counts,order_list,followup_signal,historical_delivery_note
from test_app import InlineUI,order

class BusinessUX(InlineUI,unittest.TestCase):
    def test_overview_and_late_completed_order_do_not_create_new_work(self):
        state=sample_workspace(); original=deepcopy(state)
        self.assertEqual(overview_counts(state),{'open':8,'attention':6,'awaiting':2,'overdue':1})
        row=next(r for r in order_list(state) if r['Purchase order']=='PO-1051')
        self.assertEqual(row['Status'],'Partially received'); self.assertIn('Overdue delivery',row['Needs attention'])
        late=next(r for r in order_list(state) if r['Purchase order']=='PO-1039')
        self.assertEqual(late['Status'],'Completed'); self.assertEqual(late['Outstanding'],'0')
        self.assertEqual(late['Needs attention'],'No')
        self.assertEqual(state,original)
        app=self.start(); self.pick_order(app,'PO-1039')
        self.assertTrue(any('Delivered 2 days late' in x.value for x in app.caption))
        self.assertTrue(any('Needs attention: No' in x.value for x in app.caption))
        self.assertNotIn('Review and resolve issue',[b.label for b in app.button])
        app.radio(key='po_filter_picker').set_value('Needs review').run()
        table=next(x for x in app.dataframe if x.key and x.key.startswith('purchase-order-table-'))
        self.assertNotIn('PO-1039',list(table.value['Purchase order']))
        self.assertIn('PO-1051',list(table.value['Purchase order']))

    def test_search_selected_order_and_inline_mode_survive_reruns(self):
        app=self.start(); app.text_input(key='po-search').set_value('lunch box').run()
        self.pick_order(app,'PO-1078'); self.open_update(app)
        app.run(); self.assertEqual(app.session_state['active_order'],'PO-1078')
        self.assertEqual(app.session_state['inline_panel']['kind'],'update')
        self.assertEqual(app.text_input(key='po-search').value,'lunch box')
        self.click(app,'Close entry form')
        self.assertFalse(app.segmented_control)
        app.text_input(key='po-search').set_value('NOT-AN-ORDER').run()
        self.assertTrue(any('No orders match' in i.value for i in app.info))
        self.assertTrue(any('PO-1078 · Needs attention' in m.value for m in app.markdown))
        self.click(app,'Show selected order')
        self.assertEqual(app.text_input(key='po-search').value,'')
        self.assertEqual(app.session_state['active_order'],'PO-1078')

    def test_draft_survives_switching_panels_and_orders_without_saving(self):
        app=self.start(); self.open_update(app)
        next(t for t in app.text_area if t.label=='Supplier notes (optional)').set_value('Latest supplier message to verify').run()
        key='confirmation-lines-PO-1042-manual-False-0'
        app.session_state[key]={'edited_rows':{0:{'quantity':'750'}},'added_rows':[],'deleted_rows':[]}
        app.run(); self.click(app,'Review and resolve issue')
        self.assertNotIn('Supplier notes (optional)',[x.label for x in app.text_area])
        self.assertIn('Assess the impact',[x.label for x in app.button])
        self.open_update(app); self.assertNotIn('Assess the impact',[x.label for x in app.button])
        self.pick_order(app,'PO-1078')
        self.assertIsNone(app.session_state['inline_panel'])
        self.pick_order(app,'PO-1042'); self.open_update(app)
        self.assertEqual(next(t for t in app.text_area if t.label=='Supplier notes (optional)').value,'Latest supplier message to verify')
        self.assertEqual(app.session_state['table_drafts'][key][0]['quantity'],'750')
        self.assertEqual(make_case(app.session_state['supplyops'],'PO-1042')['delivery_totals'][0]['latest_confirmed'],'800')
        self.click(app,'Save supplier update')
        self.assertIsNone(app.session_state['inline_panel'])
        self.assertEqual(make_case(app.session_state['supplyops'],'PO-1042')['delivery_totals'][0]['latest_confirmed'],'750')

    def test_assign_followup_updates_order_and_reuses_current_review(self):
        app=self.start(); self.click(app,'Review and resolve issue')
        for title in ['What happened?','Why it matters','What needs checking','Recommended next step']:
            self.assertTrue(any(title in m.value for m in app.markdown))
        self.assertEqual(len(app.session_state['supplyops']['investigations']),0)
        self.click(app,'Assess the impact'); self.click(app,'Decide next action')
        next(r for r in app.radio if r.label=='What will you do?').set_value('Assign follow-up').run()
        self.assertNotIn('Supplier message',[t.label for t in app.text_area])
        next(t for t in app.text_area if t.label=='Action to complete').set_value('Confirm allocation and the balance delivery date.').run()
        next(t for t in app.text_input if t.label=='Responsible owner').set_value('Operations owner').run()
        next(t for t in app.date_input if t.label=='Due date').set_value(date(2026,11,11)).run()
        self.click(app,'Save action')
        self.assertEqual(app.session_state['active_order'],'PO-1042')
        self.assertIsNone(app.session_state['inline_panel'])
        self.assertTrue(any('Operations owner' in m.value and '11 Nov 2026' in m.value for m in app.markdown))
        self.click(app,'Review and resolve issue'); app.run()
        self.assertEqual(len(app.session_state['supplyops']['investigations']),1)

    def test_delay_supplier_draft_and_commercial_escalation_inline(self):
        app=self.start(); self.pick_order(app,'PO-1078'); self.click(app,'Review and resolve issue')
        self.assertEqual(next(m for m in app.metric if m.label=='Delay').value,'14 days')
        self.click(app,'Assess the impact'); self.click(app,'Decide next action')
        draft=next(t for t in app.text_area if t.label=='Supplier message').value
        self.assertNotIn('(fictional)',draft)
        self.assertIn('26 Nov 2026',draft)
        self.pick_order(app,'PO-1095'); self.click(app,'Review and resolve issue')
        self.assertEqual(next(m for m in app.metric if m.label=='Price difference').value,'EUR 400.00')
        self.click(app,'Assess the impact'); self.click(app,'Decide next action')
        next(r for r in app.radio if r.label=='What will you do?').set_value('Escalate for review').run()
        next(t for t in app.text_area if t.label=='Reason for escalation').set_value('Review the EUR 400 change and advance-payment proposal.').run()
        next(t for t in app.text_input if t.label=='Responsible owner').set_value('Commercial owner').run()
        next(t for t in app.date_input if t.label=='Next review date').set_value(date(2026,11,11)).run()
        self.click(app,'Save action')
        state=app.session_state['supplyops']; action=events_for(state,'PO-1095','followup_action')[-1]['payload']
        self.assertEqual(action['status'],'Internally escalated')
        self.assertEqual(state['orders']['PO-1095']['lines'][0]['unit_price'],'8')
        self.assertFalse(action['message_sent']); self.assertEqual(app.session_state['active_order'],'PO-1095')

    def test_multi_product_receipts_accumulate_only_entered_quantities(self):
        state=empty_workspace(); po=order('PO-MULTI','UI-01',qty='50')
        po['lines'].append({**po['lines'][0],'sku':'UI-02'})
        create_order(state,po,'2026-11-01'); record_confirmation(state,'PO-MULTI',po['lines'],'2026-11-02')
        app=AppTest.from_file('app.py'); app.session_state['supplyops']=state; app.run(timeout=30)
        self.open_update(app,receipt=True)
        app.session_state['receipt-lines-PO-MULTI-0']={'edited_rows':{0:{'quantity':'10'}},'added_rows':[],'deleted_rows':[]}
        self.click(app,'Save goods received')
        t=make_case(app.session_state['supplyops'],'PO-MULTI')['delivery_totals']
        self.assertEqual([x['physically_received'] for x in t],['10','0'])
        self.open_update(app,receipt=True)
        app.session_state['receipt-lines-PO-MULTI-1']={'edited_rows':{0:{'quantity':'15'},1:{'quantity':'5'}},'added_rows':[],'deleted_rows':[]}
        self.click(app,'Save goods received')
        t=make_case(app.session_state['supplyops'],'PO-MULTI')['delivery_totals']
        self.assertEqual([x['physically_received'] for x in t],['25','5'])
        self.assertEqual([x['latest_confirmed'] for x in t],['50','50'])
        self.assertEqual([x['outstanding_confirmed'] for x in t],['25','45'])
        self.assertEqual(app.session_state['supplyops']['support']['PO-MULTI'],{})
        other=self.start(); self.assertNotIn('PO-MULTI',other.session_state['supplyops']['orders'])

    def test_saving_one_order_does_not_discard_another_orders_draft(self):
        app=self.start(); self.open_update(app)
        key='confirmation-lines-PO-1042-manual-False-0'
        app.session_state[key]={'edited_rows':{0:{'quantity':'750'}},'added_rows':[],'deleted_rows':[]}
        app.run(); self.pick_order(app,'PO-1078'); self.open_update(app)
        self.click(app,'Save supplier update')
        self.pick_order(app,'PO-1042'); self.open_update(app)
        self.assertEqual(app.session_state['table_drafts'][key][0]['quantity'],'750')
        self.click(app,'Save supplier update')
        self.assertEqual(make_case(app.session_state['supplyops'],'PO-1042')['delivery_totals'][0]['latest_confirmed'],'750')
        self.assertEqual(app.session_state['active_order'],'PO-1042')

    def test_empty_findings_sections_are_omitted(self):
        app=AppTest.from_string("from ui_helpers import findings_view\nfindings_view({'summary':'Review complete.','changed':[],'implications':[],'missing':[],'steps':[]})").run()
        self.assertFalse(app.exception)
        text=' '.join(m.value for m in app.markdown)
        self.assertIn('Key finding',text); self.assertNotIn('Information to confirm',text)
        self.assertNotIn('Business impact',text)

    def test_retained_document_review_correction_and_save_inline(self):
        app=self.start(); self.open_update(app)
        document=BytesIO(b'Order ID: PO-1042\nSupplier ID: SUP-NORD\nSupplier: Nordlicht Manufacturing\nPayment terms: Net 30\nSKU | description | quantity | unit_price | currency | delivery_date\nBOT-750 | Insulated bottle | 750 | 12.50 | EUR | 2026-11-12')
        document.name='supplier-update.txt'
        app.session_state['pending_uploads']={'confirm-file-PO-1042-0':document}
        app.run(); self.click(app,'Read document')
        self.assertTrue(any('Document read.' in x.value for x in app.info))
        self.assertEqual(make_case(app.session_state['supplyops'],'PO-1042')['delivery_totals'][0]['latest_confirmed'],'800')
        key=next(key for key in app.session_state['table_drafts'] if key.startswith('confirmation-lines-') and '-True-0' in key)
        app.session_state[key]={'edited_rows':{0:{'quantity':'775'}},'added_rows':[],'deleted_rows':[]}
        app.run(); self.click(app,'Close entry form'); self.open_update(app)
        self.assertEqual(app.session_state['table_drafts'][key][0]['quantity'],'775')
        self.click(app,'Save supplier update')
        state=app.session_state['supplyops']; self.assertEqual(make_case(state,'PO-1042')['delivery_totals'][0]['latest_confirmed'],'775')
        event=events_for(state,'PO-1042','confirmation')[-1]
        self.assertEqual(event['payload']['attachment']['filename'],'supplier-update.txt')
        self.assertNotIn('data',event['payload']['attachment'])
        self.assertEqual(app.session_state['evidence_files'][event['id']]['data'],document.getvalue())
        self.assertIsNone(app.session_state['inline_panel'])

class AttentionRules(unittest.TestCase):
    def test_late_history_and_old_review_do_not_require_attention(self):
        state=sample_workspace(); iid='PO-1039|JAR-500|late_receipt'; original=deepcopy(events_for(state,'PO-1039','receipt'))
        findings=prepared_investigation(state,iid); save_investigation(state,iid,findings,findings['trace'],'Evidence summary')
        self.assertTrue(state['issues'][iid]['detected'])
        self.assertFalse(requires_attention(state,state['issues'][iid])); self.assertEqual(issue_groups(state,'PO-1039'),[])
        self.assertEqual(order_status(state,'PO-1039'),'Completed')
        self.assertIn('Delivered 2 days late',historical_delivery_note(state,'PO-1039','JAR-500'))
        self.assertEqual(events_for(state,'PO-1039','receipt'),original)

    def test_explicit_pending_late_delivery_followup_requires_attention(self):
        state=sample_workspace(); iid='PO-1039|JAR-500|late_receipt'
        record_action(state,iid,'Open','Supplier quality','2026-11-11','Review the cause of the late delivery.')
        self.assertTrue(requires_attention(state,state['issues'][iid]))
        self.assertEqual(len(issue_groups(state,'PO-1039')),1)
        self.assertEqual(overview_counts(state)['attention'],7)
        app=AppTest.from_file('app.py'); app.session_state['supplyops']=state; app.run(timeout=30)
        table=next(x for x in app.dataframe if x.key and x.key.startswith('purchase-order-table-'))
        row=next(i for i,r in table.value.iterrows() if r['Purchase order']=='PO-1039')
        app.session_state[table.key]={'selection':{'rows':[int(row)],'columns':[],'cells':[]}}; app.run()
        self.assertIn('Review and resolve issue',[b.label for b in app.button])
        self.assertTrue(any('PO-1039 · Completed' in m.value for m in app.markdown))
        record_action(state,iid,'Resolved','Supplier quality',None,'Supplier quality review complete.',resolution_type='authorized_exception',approving_party='Quality manager',decision='Close the historical delivery exception',reason='Cause reviewed; no remaining action')
        self.assertFalse(requires_attention(state,state['issues'][iid]))
        self.assertTrue(state['issues'][iid]['detected'])

    def test_completed_order_can_still_need_commercial_review(self):
        state=sample_workspace(); record_receipt(state,'PO-1095',[{'sku':'TOTE-01','quantity':'500'}],'2026-11-10')
        self.assertEqual(order_status(state,'PO-1095'),'Completed')
        self.assertEqual(len(issue_groups(state,'PO-1095')),2)
        row=next(r for r in order_list(state) if r['Purchase order']=='PO-1095')
        self.assertEqual(row['Status'],'Completed'); self.assertIn('Unit price changed',row['Needs attention'])
        self.assertEqual(row['Outstanding'],'0')

if __name__=='__main__': unittest.main()
