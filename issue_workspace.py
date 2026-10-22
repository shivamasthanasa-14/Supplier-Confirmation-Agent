"""Guided issue resolution UI; domain records remain owned by operations."""
from datetime import date
import streamlit as st
from presentation import business_text,status_label,issue_title,supplier_draft,price_difference
from operations import (make_case,events_for,prepared_investigation,
                        save_investigation,record_action,set_support,issue_groups,related_issue_ids,
                        investigation_stale,COMMERCIAL_KINDS)
from core import compare
from workflow import amount,day,SUPPORT_LABELS,SUPPORT_FIELDS,support_rows,support_records
from ui_helpers import findings_view,trace_view,history_view,edit_table,TOOL_LABELS,reconciliation_view,findings_evidence_view
from agent import client_for,investigate,AgentFailure


def open_issue(issue_id,origin='po'):
    st.session_state['issue_route']={'view':'detail','id':issue_id,'origin':origin}
    st.session_state.setdefault('issue_stages',{}).setdefault(issue_id,1)


def render(state,commit,go,live_enabled,api_key,model):
    # Streamlit removes widgets when their stage is hidden. Retain employee edits
    # independently so returning to a stage restores the same draft and fields.
    retained=st.session_state.setdefault('issue_field_values',{})
    for key in list(st.session_state):
        if key.startswith('action-'):
            retained[key]=st.session_state[key]
    for key,value in retained.items():
        if key not in st.session_state: st.session_state[key]=value
    st.markdown('##### Review and resolve issue')
    route=st.session_state.get('issue_route',{})
    iid=route.get('id')
    if iid not in state['issues'] or state['issues'][iid]['order_id']!=st.session_state['active_order']:
        go('Purchase Orders',st.session_state['active_order'])
    issue=state['issues'][iid]; oid=issue['order_id']; po=state['orders'][oid]
    related_ids=related_issue_ids(state,iid)
    active_related=[state['issues'][key] for key in related_ids if state['issues'][key]['detected']]
    commercial=issue['kind'] in COMMERCIAL_KINDS
    st.session_state['active_order']=oid
    st.caption(issue['sku']+' · '+status_label(issue['status']))
    st.write('**Owner:** '+(issue['owner'] or 'Unassigned')+' · **Next follow-up:** '+(day(issue['next_followup']) if issue['next_followup'] else 'Not set'))
    other=issue_groups(state,oid)
    if not any(i['id']==iid for i in other):
        other=[i for i in other if iid not in i['related_ids']]+[{**issue,'related_ids':related_ids}]
    if len(other)>1:
        choice=st.selectbox('Issues on this order',[i['id'] for i in other],index=next(n for n,i in enumerate(other) if i['id']==iid),
            format_func=lambda key:state['issues'][key]['sku']+' · '+issue_title(state['issues'][key]),key='switch-issue-'+iid)
        if choice!=iid: open_issue(choice,route['origin']); st.rerun()
    stages=st.session_state.setdefault('issue_stages',{})
    stage=stages.setdefault(iid,1)
    runs=[r for r in state['investigations'] if r['issue_id'] in related_ids or iid in r.get('related_issue_ids',[])]
    latest=runs[-1] if runs else None
    stale=bool(latest and investigation_stale(state,latest))
    names=['Understand the issue','Assess the impact','Review findings','Decide next action']
    st.caption('Step '+str(stage)+' of 4 · '+names[stage-1])

    def move(value):
        for key in list(st.session_state):
            if key.startswith('action-'):
                retained[key]=st.session_state[key]
        stages[iid]=value; st.rerun()

    def run():
        case=make_case(state,oid)
        case['issue_context']={k:issue[k] for k in ['id','sku','kind','title','detail','detected']}
        case['related_supply_alerts']=[{k:i[k] for k in ['id','kind','title','detail','detected']} for i in active_related] if not commercial else []
        case['issue_context']['current_reconciliation']=next(t for t in case['delivery_totals'] if t['sku']==issue['sku'])
        if live_enabled:
            if st.session_state.get('investigation_count',0)>=3:
                st.session_state['issue_failure_'+iid]='The live review limit for this visit has been reached. Review the available records instead.'
                return
            st.session_state['investigation_count']=st.session_state.get('investigation_count',0)+1
            try:
                with st.status('Assessing business impact…',expanded=True) as progress:
                    def activity(step):
                        progress.write(('Checked: ' if step['evidence']['status']=='available' else 'Unavailable: ')+TOOL_LABELS[step['tool']])
                    with client_for(api_key) as client:
                        result=investigate(case,'Commercial terms' if issue['kind'] in ('price_change','payment_change') else issue['title'],'',{},client,model,on_activity=activity)
                    progress.update(label='Review complete',state='complete',expanded=False)
                findings=result['findings']; trace=result['trace']; mode='Live Gemini investigation'
            except Exception as exc:
                st.session_state['issue_failure_'+iid]="We couldn't complete this review. Your order information has not changed. Try again or review the available records."
                st.session_state['failed_reads_'+iid]=exc.trace if isinstance(exc,AgentFailure) else []
                return
        else:
            with st.spinner('Checking the order, supplier update and supporting records…'):
                findings=prepared_investigation(state,iid); trace=findings['trace']
            mode='Prepared example investigation' if oid in state['sample_orders'] else 'Evidence summary · custom records'
        commit(save_investigation,iid,findings,trace,mode,'')
        st.session_state.pop('issue_failure_'+iid,None)
        st.session_state.pop('issue_completion_'+iid,None)
        move(3)

    if stage==1:
        st.markdown('#### What happened?')
        case=make_case(state,oid); total=next(t for t in case['delivery_totals'] if t['sku']==issue['sku'])
        original=next(x for x in po['lines'] if x['sku']==issue['sku'])
        confirmed=next(x for x in case['confirmation']['lines'] if x['sku']==issue['sku'])
        st.write(business_text(issue['detail']))
        if commercial:
            a,b,c=st.columns(3)
            a.metric('Ordered unit price',original['currency']+' '+amount(original['unit_price'],2))
            b.metric('Confirmed unit price',original['currency']+' '+amount(confirmed.get('unit_price'),2))
            row=next(r for r in compare(po,case['confirmation']) if r['SKU']==issue['sku'])
            c.metric('Price difference',price_difference(row.get('total_variance'),original['currency']))
            st.write('Payment terms: '+po['payment_terms']+' → '+(confirmed.get('payment_terms') or 'Not provided'))
        elif any(i['kind']=='delivery_delay' for i in active_related):
            a,b,c=st.columns(3)
            a.metric('Requested delivery',day(total['original_requested_date']))
            b.metric('Expected delivery',day(total['current_promised_date']))
            days=(date.fromisoformat(total['current_promised_date'])-date.fromisoformat(total['original_requested_date'])).days
            c.metric('Delay',str(days)+' days')
        # Local record calculations make the overview useful before any external
        # review. No model is called and no investigation is recorded here.
        overview=prepared_investigation(state,iid)
        st.markdown('#### Why it matters')
        impacts=overview['implications']
        important=next((item for item in impacts if 'variance' in item or 'possible gap' in item),impacts[0] if impacts else 'The supplier update needs review before deciding the next action.')
        st.write(business_text(important))
        st.markdown('#### What needs checking')
        checks=overview['missing'] or (['Verify stock allocation and arrival timing before treating any customer delivery risk as confirmed.'] if not commercial else ['Confirm whether the commercial owner has agreed to the proposed terms.'])
        for item in checks[:2]: st.write('• '+business_text(item))
        st.markdown('#### Recommended next step')
        st.write(business_text(overview['steps'][0]))
        with st.expander('Order and supplier details'):
            reconciliation_view([total])
            if not commercial:
                for item in active_related: st.write(issue_title(item)+': '+business_text(item['detail']))
        if not active_related: st.info('The discrepancy has been corrected in the latest records. Goods received remain recorded separately.')
        if stale: st.warning('Previous findings are outdated. Assess the updated records before saving an action.')
        if st.button('Assess the impact',type='primary'): move(2)
        if latest and st.button('Review latest findings'): move(3)

    elif stage==2:
        st.markdown('#### Assess business impact')
        failure=st.session_state.get('issue_failure_'+iid)
        if not failure:
            run(); st.rerun()
        else:
            st.error(failure)
            with st.expander('Supporting evidence'): trace_view(st.session_state.get('failed_reads_'+iid,[]),'failed-'+iid)
            if st.button('Try review again',type='primary'):
                st.session_state.pop('issue_failure_'+iid,None); run(); st.rerun()
            if st.button('Review available records'):
                findings=prepared_investigation(state,iid)
                commit(save_investigation,iid,findings,findings['trace'],'Evidence summary after incomplete live attempt',''); move(3)

    elif stage==3:
        if not latest: move(1)
        st.markdown('#### Review findings')
        if stale:
            st.warning('These findings are outdated. The order information has changed or the earlier review is incomplete. Assess the updated information before choosing an action.')
        st.caption('Live AI review' if latest['mode']=='Live Gemini investigation' else 'Available-records review · no live AI run')
        findings_view(latest['findings'])
        with st.expander('Supporting evidence'):
            st.caption('Records checked during the live AI review.' if latest['mode']=='Live Gemini investigation' else 'Records used for this review.')
            findings_evidence_view(latest['findings'])
            trace_view(latest['trace'],latest['id'])
        if latest['findings'].get('missing'):
            with st.expander('Add information to complete the review'):
                st.write('Add the specific missing record identified above, or continue with the limits shown in the findings.')
                kinds=['terms'] if issue['kind'] in ('price_change','payment_change') else ['inventory','commitments']
                if any('alternative' in item.lower() for item in latest['findings']['missing']): kinds.append('alternatives')
                if issue['kind']=='missing_confirmation':
                    if st.button('Record missing supplier confirmation'): go('Supplier Updates',oid,update_type='Supplier confirmation or revised promise')
                kind=st.selectbox('Information to add',kinds,format_func=lambda k:SUPPORT_LABELS[k],key='missing-kind-'+iid)
                existing=state['support'].get(oid,{}).get(kind,{})
                fields=[f for f in SUPPORT_FIELDS[kind] if f!='supplier_id']
                with st.form('missing-'+iid+'-'+kind):
                    rows=edit_table(support_rows(existing,kind),fields,'missing-records-'+iid+'-'+kind)
                    empty=st.checkbox('No customer commitments for this product') if kind=='commitments' else False
                    save=st.form_submit_button('Save information')
                if save:
                    try:
                        populated=[r for r in rows if any(v not in (None,'') for v in r.values())]
                        if kind=='terms': populated=[{**r,'supplier_id':po['supplier_id']} for r in populated]
                        records={issue['sku']:[]} if empty else support_records(populated,kind)
                        commit(set_support,oid,kind,records); st.rerun()
                    except (ValueError,TypeError,KeyError,OSError): st.error('Check the product codes, quantities and dates before saving.')
        if st.button('Assess updated information',type='primary' if stale else 'secondary'):
            st.session_state.pop('issue_failure_'+iid,None); move(2)
        if st.button('Decide next action',type='secondary' if stale else 'primary',disabled=stale): move(4)

    elif stage==4:
        if not latest: move(1)
        st.markdown('#### Decide next action')
        if stale: st.warning('Previous findings are outdated. Earlier actions remain in the history.')
        if stale:
            st.warning('The order information has changed. Assess the updated information before saving this action.')
            if st.button('Assess updated information',type='primary'): move(2)
        else:
            st.write('**Recommended action:** '+business_text(next(iter(latest['findings'].get('steps',[])),'Review the issue with the responsible employee.')))
            choices=['Request supplier clarification','Escalate for review','Assign follow-up','Mark issue resolved','Close with documented approval']
            choice=st.radio('What will you do?',choices,key='action-choice-'+iid)
            key=iid+'-'+latest['id']+'-'+choice
            draft=''; owner=issue['owner']; due=None; approver=''; decision=''; reason=''; resolution=''
            closing=choice in choices[3:]
            if choice=='Request supplier clarification':
                draft=st.text_area('Supplier message',value=supplier_draft(latest['findings']['draft'],latest['findings'].get('reconciliation',[])),height=220,max_chars=7000,key='action-draft-'+key)
                st.caption('Review this draft yourself. Nothing is sent automatically; recording it does not approve revised terms.')
                note=st.text_area('Internal note (optional)',max_chars=2000,key='action-note-'+key)
            elif choice=='Escalate for review':
                note=st.text_area('Reason for escalation',max_chars=2000,key='action-note-'+key)
            elif choice=='Assign follow-up':
                note=st.text_area('Action to complete',max_chars=2000,key='action-note-'+key)
            elif choice=='Mark issue resolved':
                resolution='corrected'
                if active_related:
                    st.warning('The discrepancy is still detected. Correct the underlying records, or document an authorized exception decision.')
                    for item in active_related: st.write(business_text(item['detail']))
                else: st.success('The reviewed discrepancy is no longer detected in the latest records.')
                note=st.text_area('Resolution note',max_chars=2000,key='action-note-'+key)
                st.caption('Resolving this discrepancy does not establish full order receipt. Physical deliveries remain recorded separately.')
            else:
                resolution='authorized_exception'
                st.write('**Discrepancy remaining:**')
                for item in active_related: st.write(business_text(item['detail']))
                if not active_related: st.caption('No reviewed discrepancy remains; use corrected resolution where appropriate.')
                approver=st.text_input('Approving person or role',max_chars=200,key='action-approver-'+key)
                decision=st.text_area('Authorized business decision',max_chars=2000,key='action-decision-'+key)
                reason=st.text_area('Reason for accepting the exception',max_chars=2000,key='action-reason-'+key)
                note=reason
                st.caption('Record an authorization already obtained. SupplyOps records this decision; it does not grant approval, authorize purchases or establish physical fulfilment.')
            if not closing:
                owner=st.text_input('Responsible owner',value=issue['owner'],max_chars=100,key='action-owner-'+key)
                due_label='Next review date' if choice=='Escalate for review' else 'Due date' if choice=='Assign follow-up' else 'Next follow-up date'
                due=st.date_input(due_label,value=date.fromisoformat(issue['next_followup']) if issue['next_followup'] else None,key='action-due-'+key)
            save=st.button('Save action',type='primary',disabled=choice=='Mark issue resolved' and bool(active_related))
            if save:
                try:
                    if not closing and (not owner.strip() or due is None): raise ValueError('Record a responsible owner and next follow-up date so this action can be tracked.')
                    if choice=='Request supplier clarification' and not draft.strip(): raise ValueError('Prepare the supplier message before recording a clarification request.')
                    status={'Request supplier clarification':'Awaiting supplier','Escalate for review':'Internally escalated','Assign follow-up':issue['status'] if issue['status']!='Resolved' else 'Open','Mark issue resolved':'Resolved','Close with documented approval':'Resolved'}[choice]
                    commit(record_action,iid,status,owner,due.isoformat() if due else None,note or ('Supplier clarification requested; draft prepared for employee review.' if choice=='Request supplier clarification' else ''),draft,
                        action_type=choice,resolution_type=resolution,approving_party=approver,decision=decision,reason=reason,related_ids=related_ids)
                    details=status_label(status)+' · Owner: '+(owner or 'Unassigned')+(' · Follow-up '+day(due.isoformat()) if due else '')
                    st.session_state['order_notice']={'order_id':oid,'message':'Action saved. '+details+'. Nothing was sent to the supplier.'}
                    st.session_state.pop('issue_completion_'+iid,None)
                    stages[iid]=3
                    go('Purchase Orders',oid)
                except (ValueError,OSError) as exc: st.error(business_text(exc))

    if stage>1 and st.button('Back to understand the issue' if stage in (2,3) else 'Back to review findings'): move(1 if stage in (2,3) else 3)
    if st.button('Close issue review'): go('Purchase Orders',oid)
    with st.expander('Previous actions and reviews'):
        for h in issue['history']:
            st.write(day(h['on'])+' · '+business_text(h['event'])+' · '+business_text(h.get('detail') or h.get('note') or h.get('status') or ''))
        if runs:
            previous=st.selectbox('Previous review',[r['id'] for r in runs],key='previous-review-'+iid)
            chosen=next(r for r in runs if r['id']==previous)
            st.caption('Outdated review' if investigation_stale(state,chosen) else 'Current review')
            findings_view(chosen['findings'])
        history_view([e for e in events_for(state,oid) if e['kind']=='followup_action' and iid in e['payload'].get('related_issue_ids',[e['payload']['issue_id']])],key='guided-history-'+iid)
