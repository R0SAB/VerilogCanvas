"""Readable UTF-8 schematic container with length-delimited, unescaped HDL records."""
import json
import uuid
from model import DesignError


def encode_document(doc):
    data=doc.serialize();sources=[('top','Top-level declarations',data.pop('declarations'))]
    for n in data['nodes']:
        source=n.pop('hdl_source','')
        if n['kind']=='inline': sources.append((n['id'],n['name'],source))
    boundary=uuid.uuid4().hex
    while any(boundary in source for _,_,source in sources): boundary=uuid.uuid4().hex
    records=[];chunks=[]
    for index,(owner,label,source) in enumerate(sources):
        key=f'{boundary}_{index}'
        begin=f'// ===== BEGIN HDL {key} {json.dumps(label,ensure_ascii=False)} =====\n'
        end=f'\n// ===== END HDL {key} =====\n'
        raw=source.encode('utf-8')
        records.append({'owner':owner,'label':label,'bytes':len(raw),'begin':begin.rstrip('\n'),'end':end.strip('\n')})
        chunks.append(begin.encode('utf-8')+raw+end.encode('utf-8'))
    data['hdl_records']=records
    return json.dumps(data,ensure_ascii=False,indent=2).encode('utf-8')+b'\n\n'+b'\n'.join(chunks)


def decode_document(raw):
    try:
        text=raw.decode('utf-8-sig');data,end=json.JSONDecoder().raw_decode(text.lstrip())
        consumed=len(text)-len(text.lstrip())+end;tail=text[consumed:].encode('utf-8')
        records=data.pop('hdl_records',None)
        if records is None:
            if tail.strip(): raise DesignError('Unexpected data after schematic JSON')
            return data
        nodes={n['id']:n for n in data['nodes']};seen=set()
        for record in records:
            owner=record['owner'];length=record['bytes']
            if owner in seen or type(length) is not int or not 0<=length<=20*1024*1024: raise DesignError('Invalid HDL record metadata')
            seen.add(owner);tail=tail.lstrip(b'\r\n');begin=(record['begin']+'\n').encode('utf-8')
            if not tail.startswith(begin): raise DesignError('Missing HDL section: '+record['label'])
            tail=tail[len(begin):];source=tail[:length].decode('utf-8');tail=tail[length:]
            finish=('\n'+record['end']+'\n').encode('utf-8')
            if not tail.startswith(finish): raise DesignError('Damaged or truncated HDL section: '+record['label']+'. Raw text can be recovered with recover_hdl.py.')
            tail=tail[len(finish):]
            if owner=='top': data['declarations']=source
            elif owner in nodes and nodes[owner]['kind']=='inline': nodes[owner]['hdl_source']=source
            else: raise DesignError('HDL section refers to an unknown block')
        if tail.strip(): raise DesignError('Unexpected data after HDL sections')
        if 'top' not in seen or any(n['kind']=='inline' and n['id'] not in seen for n in data['nodes']): raise DesignError('Missing HDL source record')
        return data
    except (UnicodeError,KeyError,TypeError,json.JSONDecodeError) as exc:
        raise DesignError('Damaged schematic metadata. Raw HDL sections can be recovered with recover_hdl.py: '+str(exc)) from exc
