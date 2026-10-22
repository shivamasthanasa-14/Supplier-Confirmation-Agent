"""Opt-in, single-user local snapshots; public mode never calls this writer."""
import json
from pathlib import Path
from operations import sample_workspace

def load_local(path):
    target=Path(path)
    if not target.exists(): return sample_workspace()
    if target.stat().st_size>10*1024*1024: raise ValueError('Local workspace exceeds the prototype storage limit.')
    try: state=json.loads(target.read_text(encoding='utf-8'))
    except (ValueError,OSError) as exc: raise ValueError('The local workspace could not be read. Preserve the file and restore a valid snapshot.') from exc
    required={'version','as_of','orders','events','issues','investigations','support','sample_orders'}
    if not isinstance(state,dict) or not required<=set(state) or state['version']!=2 or not isinstance(state['events'],list) or not isinstance(state['orders'],dict):
        raise ValueError('The local workspace format is invalid. The file has not been overwritten.')
    return state

def save_local(path,state):
    # Attachments and original extracted text live outside this object in session state.
    target=Path(path)
    encoded=json.dumps(state,indent=2,ensure_ascii=False)
    if len(encoded.encode('utf-8'))>10*1024*1024: raise ValueError('Local workspace exceeds the prototype storage limit.')
    target.parent.mkdir(parents=True,exist_ok=True)
    temporary=target.with_suffix('.tmp')
    temporary.write_text(encoded,encoding='utf-8')
    temporary.replace(target)
