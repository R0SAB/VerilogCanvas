"""Inline HDL interfaces and shared top-level export; source text is never reformatted on save."""
import copy
import re
from dataclasses import dataclass
from functools import lru_cache
from hdl_import import lex, body_declarations, parse_decl, split, ModuleInterface, group, CLOSE, TYPES
from model import DesignError

DEFAULT_SOURCE = "input wire a;\noutput wire y;\n\nassign y = a;\n"

@dataclass
class InlineInterface:
    inputs: list
    outputs: list
    params: dict
    body: str
    requires_sv: bool
    port_types: dict

@lru_cache(maxsize=128)
def parse_inline(source):
    if not isinstance(source,str) or '\x00' in source: raise DesignError('Inline HDL must be text without NUL characters')
    tokens=lex(source)
    forbidden={'module','endmodule','macromodule','interface','endinterface','package','endpackage','program','endprogram'}
    for t in tokens:
        if t.text in forbidden or t.text.startswith('`'):
            raise DesignError(f'Line {t.line}: {t.text} is not supported inside an Inline HDL Block. Enter a module body without a module wrapper or preprocessor directives.')
    # Catch incomplete delimiters even when they occur in executable code.
    i=0
    while i<len(tokens):
        if tokens[i].text in CLOSE: _,i=group(tokens,i)
        elif tokens[i].text in CLOSE.values(): raise DesignError(f'Line {tokens[i].line}: unmatched {tokens[i].text}')
        else: i+=1
    scopes={'generate':'endgenerate','begin':'end','case':'endcase','casex':'endcase','casez':'endcase','function':'endfunction','task':'endtask','fork':'join'}
    stack=[]
    for t in tokens:
        if t.text in scopes: stack.append((scopes[t.text],t.line))
        elif t.text in set(scopes.values())|{'join_any','join_none'}:
            closing='join' if t.text in ('join_any','join_none') else t.text
            if not stack or stack[-1][0]!=closing: raise DesignError(f'Line {t.line}: unmatched {t.text}')
            stack.pop()
    if stack: raise DesignError(f'Line {stack[-1][1]}: expected {stack[-1][0]}')
    decls=list(body_declarations(tokens));ports=[];ranges=[]
    for decl in decls:
        if decl[0].text not in ('input','output','inout','ref'): continue
        direction=None;inherited=None
        for item in split(decl):
            direction,p,inherited=parse_decl(item,direction,inherited)
            ports.append((direction,p))
        # Positions are recorded by the lexer, including comments/whitespace.
        last=next(t for t in tokens if t.start>=decl[-1].end)
        if last.text!=';': raise DesignError('Expected semicolon after a port declaration')
        ranges.append((decl[0].start,last.end,decl))
    names=[p.name for _,p in ports]
    for decl in decls:
        if decl[0].text not in TYPES: continue
        inherited=None
        for item in split(decl):
            clean=split(item,'=')[0]
            try: _,local,inherited=parse_decl(clean,'output',inherited)
            except DesignError: continue
            if local.name in names:
                raise DesignError(f'Port {local.name} is redeclared. Put its type in the input/output declaration, for example output reg {local.name};')
    header=lex('('+','.join(names)+')')
    n=ModuleInterface('canvas_inline_body',header,tokens,1).to_node('inline_body')
    port_types={}
    for start,end,decl in ranges:
        direction=None;inherited=None
        for item in split(decl):
            direction,port,inherited=parse_decl(item,direction,inherited)
            p=n.port(port.name);qualifiers={t.text for t in inherited}
            typ='wire bit' if direction=='input' and p.two_state else 'wire' if direction=='input' else next((v for v in ('bit','logic','reg','wire','integer','int','byte','shortint','longint','time') if v in qualifiers),'wire')
            if typ in ('integer','int','byte','shortint','longint','time'): typ='reg'
            port_types[p.name]=typ
    # Interface declarations belong to the editor. Everything else is emitted
    # unchanged in the top module, including comments, local names and whitespace.
    body=source
    for start,end,decl in reversed(ranges): body=body[:start]+body[end:]
    sv=any(t.text in {'logic','bit','always_ff','always_comb','always_latch','typedef','enum','struct','union','int','shortint','longint','byte','string','unique','priority'} or re.fullmatch(r"'[01xXzZ]",t.text) for t in tokens) or any(p.requires_sv() for p in n.ports())
    return InlineInterface(n.inputs,n.outputs,n.params,body,sv,port_types)


def update_interface(node,source):
    interface=parse_inline(source)
    node.hdl_source=source;node.inputs=copy.deepcopy(interface.inputs);node.outputs=copy.deepcopy(interface.outputs);node.params=copy.deepcopy(interface.params)
    node.transforms={};node.normalize()
    return interface


def flat_types(doc):
    result={}
    for node in doc.nodes:
        if node.kind!='inline': continue
        parsed=parse_inline(node.hdl_source)
        for p in node.outputs:
            result[p.name]=parsed.port_types[p.name]
    return result


def declared_signals(source):
    """Recognize built-in top-level signal declarations without modifying source."""
    result={}
    for decl in body_declarations(lex(source)):
        if decl[0].text not in TYPES: continue
        inherited=None
        for item in split(decl):
            try: _,p,inherited=parse_decl(split(item,'=')[0],'output',inherited)
            except DesignError: continue
            result[p.name]=(p,{t.text for t in inherited})
    return result


def declaration_conflict(name,old,old_params,old_origin,new,new_params,new_origin):
    def properties(port,params):
        packed,unpacked=port.dimensions_text(params)
        return {
            'packed dimensions': packed or 'scalar (1 bit)',
            'array dimensions': unpacked or 'none',
            'signedness': 'signed' if port.signed else 'unsigned',
            'state type': '2-state' if port.two_state else '4-state',
        }
    a,b=properties(old,old_params),properties(new,new_params)
    differences='\n'.join(f'  {key}: {a[key]} -> {b[key]}' for key in a if a[key]!=b[key])
    def describe(values):
        return f"{values['signedness']} {values['packed dimensions']}; arrays: {values['array dimensions']}; {values['state type']}"
    return DesignError(
        f'Conflicting declarations for shared Inline HDL signal {name}\n\n'
        f'Existing ({old_origin}):\n  {describe(a)}\n'
        f'Conflicting ({new_origin}):\n  {describe(b)}\n\n'
        f'Differences (existing -> conflicting):\n{differences}\n\n'
        'These declarations refer to the same shared signal. '
        'Make their signedness, dimensions and state type match.')


def flat_context(doc,components,nets,sv):
    """Emit each interface signal once and connect differently named ports plainly."""
    inline=[n for n in doc.nodes if n.kind=='inline']
    if not inline: return [],set()
    existing={n.name:(n.ports()[0],{},None) for n in doc.nodes if n.kind in ('input','output')}
    origins={n.name:f'top-level {n.kind} {n.name}' for n in doc.nodes if n.kind in ('input','output')}
    owners={};endpoint_owners={};drivers={};port_names={p.name for n in inline for p in n.ports()}
    for index,net in enumerate(components):
        name=nets[net.ports[0]];node,p=doc.resolve(net.source)
        if name in owners: raise DesignError(f'Disconnected nets use the same shared Inline HDL name: {name}. Connect them or use distinct names.')
        existing.setdefault(name,(p,node.params,None));origins.setdefault(name,f'driver {node.name}.{p.name}');owners[name]=index
        for ep in net.ports: endpoint_owners[ep]=index
    for node in doc.nodes:
        if node.kind in ('input','output') and node.name not in owners: owners[node.name]=('top',node.id)
    user={};user_origins={}
    for source,params,origin in [(doc.declarations,{},'top-level declarations')]+[(parse_inline(n.hdl_source).body,n.params,f'Inline HDL block {n.name}, body declaration') for n in inline]:
        for name,(p,types) in declared_signals(source).items():
            if name in user and name in port_names: raise DesignError(f'Duplicate shared signal declaration: {name}')
            user[name]=(p,params,types);user_origins[name]=origin
    for name,value in user.items():
        if name in existing and name in port_names:
            old,params,_=existing[name];p,other_params,_=value
            if (old.packed_bounds(params),old.array_bounds(params),old.signed,old.two_state)!=(p.packed_bounds(other_params),p.array_bounds(other_params),p.signed,p.two_state):
                raise declaration_conflict(name,old,params,origins[name],p,other_params,user_origins[name])
        existing[name]=value;origins[name]=user_origins[name]
    declarations=[];assignments=[];emitted_assigns=set();types=flat_types(doc)
    for node in inline:
        parsed=parse_inline(node.hdl_source)
        if parsed.requires_sv and not sv: raise DesignError(f'Inline HDL Block {node.name} requires SystemVerilog. Select .sv export.')
        for p in node.ports():
            net=nets.get((node.id,p.name))
            owner=endpoint_owners.get((node.id,p.name),('unused',node.id,p.name))
            if p.name in owners and owners[p.name]!=owner:
                raise DesignError(f'Inline port {node.name}.{p.name} names a different existing net. Use the same net or rename the port in the source.')
            owners[p.name]=owner
            if node.source(p.name):
                if p.name in drivers: raise DesignError(f'Multiple Inline HDL outputs drive shared signal {p.name}')
                drivers[p.name]=node.id
            typ=types.get(p.name,parsed.port_types[p.name])
            if p.name in existing:
                old,params,decltypes=existing[p.name]
                if (old.packed_bounds(params),old.array_bounds(params),old.signed,old.two_state)!=(p.packed_bounds(node.params),p.array_bounds(node.params),p.signed,p.two_state):
                    raise declaration_conflict(p.name,old,params,origins[p.name],p,node.params,f'Inline HDL block {node.name}, port {p.name}')
                if node.source(p.name) and typ in ('reg','logic','bit') and decltypes is not None and not decltypes.intersection({'reg','logic','bit','int','integer','byte','shortint','longint','time'}):
                    raise DesignError(f'Shared signal {p.name} must be declared as {typ} for its Inline HDL output')
            else:
                existing[p.name]=(p,node.params,None)
                origins[p.name]=f'Inline HDL block {node.name}, port {p.name}'
                declarations.append(f'{typ} {p.declaration(node.params)}{p.name}{p.suffix(node.params)};')
            if net and net!=p.name:
                assignment=f'assign {net} = {p.name};' if node.source(p.name) else f'assign {p.name} = {net};'
                if assignment not in emitted_assigns: assignments.append(assignment);emitted_assigns.add(assignment)
    return declarations+assignments,set(user)


def export_inline(node,nets,used,sv):
    interface=parse_inline(node.hdl_source)
    if interface.requires_sv and not sv: raise DesignError(f'Inline HDL Block {node.name} requires SystemVerilog. Select .sv export.')
    return [f'// Inline HDL: {node.name}',interface.body.rstrip(),'']
