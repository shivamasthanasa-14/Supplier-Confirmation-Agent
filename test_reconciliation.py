"""End-to-end current balances, chronology, and employee closure boundaries."""
from copy import deepcopy
from datetime import date
from decimal import Decimal
import unittest
from unittest.mock import Mock
import json
from types import SimpleNamespace as NS
from operations import (sample_workspace,make_case,record_confirmation,record_receipt,set_support,
    prepared_investigation,save_investigation,investigation_stale,related_issue_ids,
    issue_groups,record_action,events_for,order_status,current_confirmation)
from core import coverage_for,Records
from ui_helpers import activity_entries

OID='PO-1042'; SKU='BOT-750'; IID=OID+'|'+SKU+'|quantity_shortfall'

def totals(state): return make_case(state,OID)['delivery_totals'][0]

def review(state):
    findings=prepared_investigation(state,IID)
    save_investigation(state,IID,findings,findings['trace'],'Prepared example investigation')
    return findings

def promise(state,quantity):
    return record_confirmation(state,OID,[{'sku':SKU,'quantity':quantity,'delivery_date':'2026-11-12'}],'2026-11-10')

def receipt(state,quantity,on='2026-11-10'):
    return record_receipt(state,OID,[{'sku':SKU,'quantity':quantity}],on)

class Reconciliation(unittest.TestCase):
    def test_revised_750_is_latest_total_and_initial_800_is_history(self):
        state=sample_workspace(); initial=review(state); old=deepcopy(state['investigations'][-1])
        self.assertEqual(totals(state)['latest_confirmed'],'800')
        self.assertEqual(totals(state)['unconfirmed_quantity'],'200')
        self.assertIn('100',' '.join(initial['implications']))
        promise(state,'750')
        self.assertTrue(investigation_stale(state,old))
        result=review(state); position=totals(state)
        self.assertEqual([position[k] for k in ['latest_confirmed','physically_received','outstanding_confirmed','unconfirmed_quantity','outstanding_ordered']],['750','0','750','250','1000'])
        self.assertIn('latest supplier total 750',result['summary'])
        self.assertEqual([e['payload']['lines'][0]['quantity'] for e in events_for(state,OID,'confirmation')],['800','750'])
        self.assertEqual(state['investigations'][0],old)
        self.assertFalse(investigation_stale(state,state['investigations'][-1]))
        legacy=deepcopy(state['investigations'][-1]); legacy.pop('reconciliation_version')
        self.assertTrue(investigation_stale(state,legacy))

    def test_receipts_300_plus_450_preserve_800_promise_and_coverage(self):
        state=sample_workspace(); review(state); old=deepcopy(state['investigations'][-1])
        receipt(state,'300','2026-11-09'); after_first=review(state)
        self.assertIn('300 physically received',after_first['summary'])
        receipt(state,'450'); result=review(state); position=totals(state)
        self.assertEqual([position[k] for k in ['ordered','latest_confirmed','physically_received','outstanding_confirmed','unconfirmed_quantity','outstanding_ordered']],['1000','800','750','50','200','250'])
        self.assertTrue(investigation_stale(state,old))
        self.assertFalse(result['coverage'])
        self.assertTrue(any('same-day receipt' in item for item in result['missing']))
        # Explicitly verified usable stock already includes any usable receipts.
        set_support(state,OID,'inventory',{SKU:{'available':'150','as_of':'2026-11-10'}})
        updated=review(state)
        self.assertEqual(updated['coverage'][-1]['available_by_due'],'200')
        self.assertEqual(updated['coverage'][-1]['uncovered'],'850')
        self.assertIn('50 still promised but not received',updated['summary'])
        self.assertIn('200 not confirmed',updated['summary'])
        receipt(state,'50'); after_more=review(state)
        self.assertEqual(totals(state)['physically_received'],'800')
        self.assertEqual(totals(state)['outstanding_confirmed'],'0')
        self.assertEqual(totals(state)['outstanding_ordered'],'200')
        self.assertFalse(after_more['coverage'])
        self.assertEqual(current_confirmation(state,OID)['lines'][0]['quantity'],'800')
        self.assertEqual(order_status(state,OID),'Partially received')

    def test_related_supply_alerts_share_action_but_commercial_stays_separate(self):
        state=sample_workspace(); receipt(state,'750')
        supply=[g for g in issue_groups(state,OID) if g['kind'] not in ('price_change','payment_change')]
        self.assertEqual(len(supply),1)
        ids=related_issue_ids(state,IID)
        self.assertIn(OID+'|'+SKU+'|partial_receipt',ids)
        record_action(state,IID,'Awaiting supplier','Operations','2026-11-11','Confirm the balance.','Draft',related_ids=ids,action_type='Request supplier clarification')
        self.assertTrue(all(state['issues'][key]['status']=='Awaiting supplier' for key in ids))
        self.assertEqual(len(issue_groups(state,'PO-1095')),2)
        commercial=prepared_investigation(state,'PO-1095|TOTE-01|price_change')
        self.assertNotIn('get_inventory',[r['tool'] for r in commercial['trace']])
        delay=prepared_investigation(state,'PO-1078|LUNCH-900|delivery_delay')
        self.assertIn('14 days',' '.join(delay['changed']))
        self.assertIn('430',' '.join(delay['implications']))

    def test_authorized_exception_retains_facts_and_requires_documentation(self):
        state=sample_workspace(); receipt(state,'750'); ids=related_issue_ids(state,IID)
        before=deepcopy(state)
        with self.assertRaises(ValueError): record_action(state,IID,'Resolved','Buyer',None,'Close it.',related_ids=ids)
        self.assertEqual(state,before)
        with self.assertRaises(ValueError): record_action(state,IID,'Resolved','Buyer',None,'Accept 800.',related_ids=ids,resolution_type='authorized_exception')
        self.assertEqual(state,before)
        record_action(state,IID,'Resolved','Buyer',None,'Accept a documented reduced commitment.',related_ids=ids,resolution_type='authorized_exception',approving_party='Procurement director',decision='Accept 800 units for this exception only',reason='Approved reduction in demand',action_type='Close by authorized exception')
        event=events_for(state,OID,'followup_action')[-1]['payload']
        self.assertEqual(event['approving_party'],'Procurement director')
        self.assertTrue(event['remaining_discrepancies'])
        self.assertTrue(all(state['issues'][key]['status']=='Resolved' for key in ids))
        self.assertTrue(state['issues'][IID]['detected'])
        self.assertEqual(totals(state)['outstanding_ordered'],'250')
        self.assertEqual(order_status(state,OID),'Partially received')
        self.assertFalse(event['message_sent'])

    def test_clarification_revision_receipt_and_corrected_resolution(self):
        state=sample_workspace(); review(state); ids=related_issue_ids(state,IID)
        record_action(state,IID,'Awaiting supplier','Buyer','2026-11-11','Clarify the balance.','Reviewed draft',related_ids=ids)
        promise(state,'1000'); review(state)
        self.assertFalse(state['issues'][IID]['detected'])
        # Confirmation is not fulfilment, even when the shortfall is corrected.
        self.assertEqual(totals(state)['physically_received'],'0')
        self.assertNotEqual(order_status(state,OID),'Completed')
        record_action(state,IID,'Resolved','Buyer',None,'Revised promise now covers the full quantity; no delivery claimed.',resolution_type='corrected',related_ids=related_issue_ids(state,IID))
        self.assertEqual(state['issues'][IID]['status'],'Resolved')
        self.assertEqual(totals(state)['outstanding_ordered'],'1000')
        receipt(state,'300'); review(state); receipt(state,'700'); review(state)
        set_support(state,OID,'inventory',{SKU:{'available':'1050','as_of':'2026-11-10'}})
        review(state)
        self.assertEqual(order_status(state,OID),'Completed')
        self.assertEqual(totals(state)['outstanding_ordered'],'0')

    def test_chronological_business_timeline_and_snapshot_dates(self):
        state=sample_workspace(); promise(state,'750'); receipt(state,'300','2026-11-09'); receipt(state,'450')
        entries=activity_entries(events_for(state,OID))
        self.assertEqual([e['date'] for e in entries],sorted(e['date'] for e in entries))
        text=' '.join(e['title']+' '+' '.join(e['details']) for e in entries)
        for expected in ['Purchase order recorded','1,000 units ordered','Supplier confirmed','800 units','Supplier revised confirmation','750 units','Goods received','300 units received','Additional goods received','450 units received','cumulative receipts 750']:
            self.assertIn(expected,text)
        set_support(state,OID,'inventory',{SKU:{'available':'900','as_of':'2026-11-08'}})
        self.assertFalse(coverage_for(make_case(state,OID),SKU))
        set_support(state,OID,'inventory',{SKU:{'available':'900','as_of':'2026-11-10'}})
        coverage=coverage_for(make_case(state,OID),SKU)
        self.assertEqual(coverage[-1]['available_by_due'],'900') # No 750-unit double count.
        state['as_of']='2026-11-13'
        promise_case=make_case(state,OID)
        self.assertEqual(coverage_for(promise_case,SKU)[-1]['available_by_due'],'900')

    def test_model_receives_current_reconciliation_and_related_alerts(self):
        from agent import investigate
        from google.genai import types
        state=sample_workspace(); receipt(state,'750'); case=make_case(state,OID)
        case['issue_context']={'sku':SKU,'kind':'quantity_shortfall'}
        case['related_supply_alerts']=[state['issues'][key] for key in related_issue_ids(state,IID)]
        client=Mock(); call=NS(name='get_receipt_history',args={'order_id':OID})
        response=NS(function_calls=[call],candidates=[NS(content=types.Content(role='model',parts=[types.Part.from_function_call(name=call.name,args=call.args)]))])
        findings={k:[] for k in ['changed','implications','missing','steps']}; findings.update(summary='An older statement: 800 units still to arrive.',draft='Please confirm the outstanding plan.')
        client.models.generate_content.side_effect=[response,NS(function_calls=[],text=json.dumps(findings))]
        result=investigate(case,'Current supply situation','',{},client,'test')
        self.assertIn('50 still promised but not received',result['findings']['summary'])
        self.assertNotIn('800 units still to arrive',result['findings']['summary'])
        payload=json.loads(client.models.generate_content.call_args_list[0].kwargs['contents'][0].parts[0].text)
        self.assertEqual(payload['delivery_totals'][0]['outstanding_confirmed'],'50')
        self.assertEqual(payload['delivery_totals'][0]['unconfirmed_quantity'],'200')
        self.assertIn('partial_receipt',[i['kind'] for i in payload['related_supply_alerts']])
        case['po']['lines'].append({**case['po']['lines'][0],'sku':'OTHER-SKU'})
        with self.assertRaises(ValueError): Records(case).call('get_inventory',{'sku':'OTHER-SKU'})

    def test_overdue_arrival_and_stock_dates_limit_customer_coverage(self):
        state=sample_workspace(); receipt(state,'750','2026-11-09')
        set_support(state,OID,'inventory',{SKU:{'available':'150','as_of':'2026-11-10'}})
        self.assertEqual(coverage_for(make_case(state,OID),SKU)[-1]['available_by_due'],'200')
        state['as_of']='2026-11-13'
        result=review(state)
        self.assertEqual(result['coverage'][-1]['available_by_due'],'150')
        self.assertTrue(any('promise is overdue' in item for item in result['missing']))
        set_support(state,OID,'inventory',{SKU:{'available':'900','as_of':'2026-11-14'}})
        self.assertFalse(coverage_for(make_case(state,OID),SKU))
        self.assertTrue(any('after the workspace date' in item for item in review(state)['missing']))


from test_app import InlineUI

class UserInterfaceCycle(InlineUI,unittest.TestCase):
    def revise(self,app,quantity):
        self.open_update(app)
        app.session_state['confirmation-lines-PO-1042-manual-False-0']={'edited_rows':{0:{'quantity':quantity}},'added_rows':[],'deleted_rows':[]}
        self.click(app,'Save supplier update')
        self.assertIsNone(app.session_state['inline_panel'])
        self.click(app,'Review and resolve issue')
        self.assertTrue(any('outdated' in x.value for x in app.warning))
        self.click(app,'Assess updated information')

    def test_ui_revised_750_and_authorized_closure(self):
        app=self.start(); self.assess(app); self.revise(app,'750')
        run=app.session_state['supplyops']['investigations'][-1]
        self.assertEqual(run['reconciliation'][0]['latest_confirmed'],'750')
        self.assertEqual(run['reconciliation'][0]['unconfirmed_quantity'],'250')
        self.click(app,'Decide next action')
        next(x for x in app.radio if x.label=='What will you do?').set_value('Mark issue resolved').run()
        self.assertTrue(next(x for x in app.button if x.label=='Save action').disabled)
        next(x for x in app.radio if x.label=='What will you do?').set_value('Close with documented approval').run()
        self.assertNotIn('Supplier message',[x.label for x in app.text_area])
        self.assertFalse(app.date_input)
        self.click(app,'Save action'); self.assertTrue(app.error)
        next(x for x in app.text_input if x.label=='Approving person or role').set_value('Procurement director').run()
        next(x for x in app.text_area if x.label=='Authorized business decision').set_value('Accept a 750-unit commitment.').run()
        next(x for x in app.text_area if x.label=='Reason for accepting the exception').set_value('Documented lower demand.').run()
        self.click(app,'Save action')
        state=app.session_state['supplyops']; event=events_for(state,OID,'followup_action')[-1]['payload']
        self.assertEqual(event['resolution_type'],'authorized_exception')
        self.assertEqual(event['status'],'Resolved'); self.assertTrue(event['remaining_discrepancies'])
        self.assertEqual(totals(state)['physically_received'],'0')
        self.assertEqual(totals(state)['outstanding_ordered'],'1000')
        self.assertNotEqual(order_status(state,OID),'Completed')
        self.assertIsNone(app.session_state['inline_panel'])
        self.assertNotIn('Review and resolve issue',[x.label for x in app.button])

    def test_ui_receipt_750_is_not_a_revised_promise(self):
        app=self.start(); self.assess(app); self.open_update(app,receipt=True)
        app.session_state['receipt-lines-PO-1042-0']={'edited_rows':{0:{'quantity':'750'}},'added_rows':[],'deleted_rows':[]}
        self.click(app,'Save goods received')
        self.assertIsNone(app.session_state['inline_panel'])
        self.assertEqual(app.session_state['active_order'],OID)
        table=next(x for x in app.dataframe if 'Confirmed awaiting delivery' in x.value.columns)
        self.assertEqual(table.value.iloc[0]['Confirmed awaiting delivery'],'50')
        self.assertEqual(table.value.iloc[0]['Quantity not yet confirmed'],'200')
        self.assertEqual(table.value.iloc[0]['Remaining order quantity'],'250')
        self.click(app,'Review and resolve issue')
        self.assertTrue(any('outdated' in x.value for x in app.warning))
        self.click(app,'Assess updated information')
        run=app.session_state['supplyops']['investigations'][-1]
        t=run['reconciliation'][0]
        self.assertEqual([t[k] for k in ['latest_confirmed','physically_received','outstanding_confirmed','unconfirmed_quantity','outstanding_ordered']],['800','750','50','200','250'])
        self.assertIn('50 still promised',run['findings']['summary'])
        self.assertTrue(any('Goods received' in x.value for x in app.markdown))

    def test_ui_clarification_revision_then_corrected_resolution(self):
        app=self.start(); self.assess(app); self.click(app,'Decide next action')
        next(x for x in app.text_input if x.label=='Responsible owner').set_value('Buyer').run()
        next(x for x in app.date_input if x.label=='Next follow-up date').set_value(date(2026,11,11)).run()
        self.click(app,'Save action')
        self.assertEqual(app.session_state['supplyops']['issues'][IID]['status'],'Awaiting supplier')
        self.assertIsNone(app.session_state['inline_panel'])
        self.revise(app,'1000')
        self.click(app,'Decide next action')
        next(x for x in app.radio if x.label=='What will you do?').set_value('Mark issue resolved').run()
        self.assertFalse(next(x for x in app.button if x.label=='Save action').disabled)
        self.click(app,'Save action'); self.assertTrue(app.error)
        next(x for x in app.text_area if x.label=='Resolution note').set_value('Full quantity now promised; delivery is still outstanding.').run()
        self.click(app,'Save action')
        state=app.session_state['supplyops']
        self.assertEqual(state['issues'][IID]['status'],'Resolved')
        self.assertEqual(totals(state)['physically_received'],'0')
        self.assertNotEqual(order_status(state,OID),'Completed')
        self.assertEqual(app.session_state['active_order'],OID)

if __name__=='__main__': unittest.main()
