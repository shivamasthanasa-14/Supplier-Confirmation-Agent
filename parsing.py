"""Memory-only extraction. Ambiguous values remain absent for human verification."""
from io import BytesIO
from pathlib import Path
import json
import re
from datetime import date
from core import number

MAX_BYTES=5*1024*1024
MAX_TEXT=24000

def extract_text(name, data):
    if not data or len(data)>MAX_BYTES: raise ValueError('Use a non-empty document up to 5 MB.')
    suffix=Path(name).suffix.lower()
    if suffix=='.txt': text=data.decode('utf-8-sig')
    elif suffix=='.eml':
        from email import policy
        from email.parser import BytesParser
        message=BytesParser(policy=policy.default).parsebytes(data)
        body=message.get_body(preferencelist=('plain',))
        text='Subject: '+str(message.get('Subject',''))+'\n'+(body.get_content() if body else '')
    elif suffix=='.pdf':
        from pypdf import PdfReader
        reader=PdfReader(BytesIO(data))
        if len(reader.pages)>30: raise ValueError('Maximum 30 PDF pages.')
        text='\n'.join(p.extract_text() or '' for p in reader.pages)
    elif suffix=='.docx':
        import zipfile
        with zipfile.ZipFile(BytesIO(data)) as archive:
            if sum(x.file_size for x in archive.infolist())>20*1024*1024: raise ValueError('This Word document is too large to read. Upload a shorter version.')
        from docx import Document
        doc=Document(BytesIO(data))
        text='\n'.join([p.text for p in doc.paragraphs]+[' | '.join(c.text for c in row.cells) for table in doc.tables for row in table.rows])
    else: raise ValueError('Supported formats: PDF, DOCX, TXT.')
    if not text.strip(): raise ValueError('No readable text was found. Scanned PDFs need a text-based export or manual entry.')
    if len(text)>MAX_TEXT: raise ValueError('Document exceeds 24,000 characters. Upload a shorter extract.')
    return text

def validate(record):
    if not isinstance(record,dict) or not isinstance(record.get('lines'),list) or len(record['lines'])>30: raise ValueError('Enter order details for up to 30 products.')
    out={k:str(record[k])[:200] if record.get(k) is not None else None for k in ['order_id','supplier_id','supplier','payment_terms','notes']}
    out['lines']=[]
    for row in record['lines']:
        if not isinstance(row,dict): raise ValueError('Check the details for each product.')
        item={k:row.get(k) for k in ['sku','description','quantity','unit_price','currency','delivery_date']}
        for k in ['quantity','unit_price']:
            if item[k] in ('',None): item[k]=None
            elif number(item[k]) is None: raise ValueError(f'{"Quantity" if k=="quantity" else "Unit price"} must be zero or a positive number.')
            else: item[k]=str(number(item[k]))
        if item['delivery_date']:
            try: date.fromisoformat(item['delivery_date'])
            except (ValueError,TypeError): raise ValueError('Dates must use YYYY-MM-DD or remain blank.')
        for k in ['sku','description','currency']:
            if item[k] is not None: item[k]=str(item[k])[:200]
        out['lines'].append(item)
    skus=[x['sku'] for x in out['lines'] if x['sku']]
    if len(skus)!=len(set(skus)): raise ValueError('This product code appears more than once. Use one row per product before reviewing the confirmation.')
    return out

def parse(text):
    try: return validate(json.loads(text))
    except json.JSONDecodeError: pass
    def field(label):
        found=re.search(r'^'+label+r'\s*:\s*(.+)$',text,re.M|re.I)
        return found.group(1).strip() if found else None
    lines=[]
    # Explicit tabular header avoids guessing a column's meaning.
    rows=text.splitlines()
    for index,row in enumerate(rows):
        if [s.strip().lower() for s in row.split('|')]==['sku','description','quantity','unit_price','currency','delivery_date']:
            for following in rows[index+1:]:
                parts=[s.strip() or None for s in following.split('|')]
                if len(parts)!=6: break
                lines.append(dict(zip(['sku','description','quantity','unit_price','currency','delivery_date'],parts)))
    oid=field('Order ID') or (re.search(r'\bPO-\d+\b',text).group() if re.search(r'\bPO-\d+\b',text) else None)
    return validate(dict(order_id=oid,supplier_id=field('Supplier ID'),supplier=field('Supplier'),payment_terms=field('Payment terms'),notes=field('Notes'),lines=lines or [dict(sku=None,description=None,quantity=None,unit_price=None,currency=None,delivery_date=None)]))

def parse_support(text, kind):
    """Explicit, documented JSON support schema; no inference from free text offline."""
    record=json.loads(text)
    if not isinstance(record,dict) or len(record)>30: raise ValueError('Enter supporting details for up to 30 products or suppliers.')
    for key,value in record.items():
        if not isinstance(key,str) or len(key)>80: raise ValueError('Check the product or supplier reference.')
        if kind=='inventory':
            if not isinstance(value,dict) or number(value.get('available')) is None: raise ValueError('Enter the usable stock quantity and the date it was checked.')
            date.fromisoformat(value['as_of'])
        elif kind=='commitments':
            if not isinstance(value,list) or len(value)>100: raise ValueError('Enter up to 100 customer delivery commitments.')
            for row in value:
                if number(row.get('quantity')) is None: raise ValueError('Commitment quantity missing or invalid.')
                date.fromisoformat(row['due'])
        elif kind=='terms':
            if not isinstance(value,dict): raise ValueError('Check the agreed supplier terms.')
            if value.get('valid_until'): date.fromisoformat(value['valid_until'])
            if not isinstance(value.get('unit_prices',{}),dict): raise ValueError('Agreed prices must identify the product.')
            if any(number(v) is None for v in value.get('unit_prices',{}).values()): raise ValueError('Enter valid agreed unit prices.')
        elif kind=='alternatives':
            if not isinstance(value,list): raise ValueError('Check the alternative supplier details.')
            for row in value:
                if number(row.get('quantity')) is None: raise ValueError('Add the available quantity for each alternative.')
                if row.get('earliest_arrival'): date.fromisoformat(row['earliest_arrival'])
    return record

def parse_support_document(text,kind):
    """Read known data formats; otherwise leave interpretation to AI or human review."""
    from workflow import support_records, SUPPORT_FIELDS
    try: return parse_support(text,kind)
    except json.JSONDecodeError: pass
    aliases={'product code':'sku','product':'sku','stock':'available','available units':'available','quantity available':'available','stock checked on':'as_of','as of':'as_of','customer / channel':'customer','units':'quantity','delivery commitment':'due','due date':'due','delivery date':'due','supplier reference':'supplier_id','price per unit':'unit_price','unit price':'unit_price','payment terms':'payment_terms','valid until':'valid_until','earliest arrival':'earliest_arrival','availability / conditions':'status'}
    lines=text.splitlines()
    for i,line in enumerate(lines):
        headers=[aliases.get(x.strip().lower(),x.strip().lower()) for x in line.split('|')]
        required={'inventory':{'sku','available','as_of'},'commitments':{'sku','quantity','due'},'terms':{'supplier_id','payment_terms'},'alternatives':{'sku','supplier','quantity'}}[kind]
        if required<=set(headers):
            rows=[]
            for line in lines[i+1:]:
                parts=[x.strip() or None for x in line.split('|')]
                if len(parts)!=len(headers): break
                rows.append({k:v for k,v in zip(headers,parts) if k in SUPPORT_FIELDS[kind]})
            if rows: return support_records(rows,kind)
    raise ValueError('These details need checking. Add the relevant quantities, dates or terms in the table below.')
