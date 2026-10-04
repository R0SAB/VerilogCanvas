"""Document model and deterministic Verilog/SystemVerilog generation (no GUI dependency)."""
from __future__ import annotations
import ast
import copy
import json
import math
import re
import shutil
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path

GRID = 20
COORD_LIMIT = 100_000_000  # Keeps zoomed Tk coordinates comfortably inside signed 32-bit limits.
# IEEE Verilog keywords; reject these for simple identifiers.
KEYWORDS = set('always and assign automatic begin buf bufif0 bufif1 case casex casez cell cmos config deassign default defparam design disable edge else end endcase endconfig endfunction endgenerate endmodule endprimitive endspecify endtable endtask event for force forever fork function generate genvar highz0 highz1 if ifnone incdir include initial inout input instance integer join large liblist library localparam macromodule medium module nand negedge nmos nor noshowcancelled not notif0 notif1 or output parameter pmos posedge primitive pull0 pull1 pulldown pullup pulsestyle_onevent pulsestyle_ondetect rcmos real realtime reg release repeat rnmos rpmos rtran rtranif0 rtranif1 scalared showcancelled signed small specify specparam strong0 strong1 supply0 supply1 table task time tran tranif0 tranif1 tri tri0 tri1 triand trior trireg unsigned use vectored wait wand weak0 weak1 while wire wor xnor xor'.split())
KEYWORDS.update('accept_on alias always_comb always_ff always_latch assert assume before bind bins binsof bit break byte chandle checker class clocking const constraint context continue cover covergroup coverpoint cross dist do endchecker endclass endclocking endgroup endinterface endpackage endprogram endproperty endsequence enum expect export extends extern final first_match foreach forkjoin global iff ignore_bins illegal_bins implements implies import inside int interconnect interface intersect join_any join_none let local logic longint matches modport nettype new null package packed priority program property protected pure rand randc randcase randsequence ref reject_on restrict return s_always s_eventually s_nexttime s_until s_until_with sequence shortint shortreal soft solve static string strong struct super sync_accept_on sync_reject_on tagged this throughout timeprecision timeunit type typedef union unique unique0 until until_with untyped var virtual void wait_order weak wildcard with within'.split())
IDENT = re.compile(r'^[A-Za-z_][A-Za-z0-9_$]*$')

class DesignError(ValueError):
    pass

def identifier(value: str) -> str:
    if not isinstance(value, str) or not IDENT.fullmatch(value) or value in KEYWORDS:
        raise DesignError(f'Invalid Verilog identifier: {value!r}')
    return value

def uid() -> str:
    return uuid.uuid4().hex

def snap(value):
    return round(value / GRID) * GRID

def expression(value: str) -> str:
    value = value.strip()
    if not value or any(c in value for c in '\n\r'):
        raise DesignError('A parameter value must be a single Verilog expression without comments or semicolons')
    stack = []
    quote = False
    escaped = False
    pairs = {')': '(', ']': '[', '}': '{'}
    for index,c in enumerate(value):
        if quote:
            if escaped: escaped = False
            elif c == '\\': escaped = True
            elif c == '"': quote = False
        elif c == '"': quote = True
        elif c == ';' or value[index:index+2] in ('//','/*','*/'):
            raise DesignError('Comments and semicolons are allowed only inside a parameter string literal')
        elif c in '([{': stack.append(c)
        elif c in ')]}':
            if not stack or stack.pop() != pairs[c]: raise DesignError('Mismatched brackets in parameter')
    if quote or stack: raise DesignError('Incomplete parameter expression')
    return value

def transform_expression(value, signal='signal'):
    """Replace standalone $ tokens, never strings, escaped names or $functions."""
    if not isinstance(value,str): raise DesignError('A transform must be text')
    value=expression(value)
    token=re.compile(r'"(?:\\.|[^"\\])*"|\\\S+|[A-Za-z_$][A-Za-z0-9_$]*')
    count=0
    def replace(match):
        nonlocal count
        if match.group()=='$':
            count+=1; return signal
        return match.group()
    result=token.sub(replace,value)
    if not count: raise DesignError('A transform must contain $ to represent the connected signal')
    return result

def parameter_value(name, params, active=()):
    """Inline references to other instance overrides, preserving strings/literals."""
    if name in active: raise DesignError(f'Circular parameter reference: {name}')
    token = re.compile(r'"(?:\\.|[^"\\])*"|(?:\d+)?\'[sS]?[bBoOdDhH][0-9a-fA-F_xXzZ?]+|`?[A-Za-z_$][A-Za-z0-9_$]*')
    value=expression(params[name])
    def replace(match):
        word=match.group(0)
        before=value[:match.start()].rstrip(); after=value[match.end():].lstrip()
        qualified=before.endswith(('::','.')) or after.startswith('::')
        if word in params and not qualified:
            return '('+parameter_value(word,params,(*active,name))+')'
        return word
    return token.sub(replace,value)

def integer_expr(value: str, params: dict[str, str], active=()) -> int:
    """Safe constant subset, used only to determine bus widths. Never eval()."""
    value = value.strip()
    def literal(m):
        digits = m.group(3).replace('_', '')
        number = int(digits, {'b': 2, 'o': 8, 'd': 10, 'h': 16}[m.group(2).lower()])
        size = int(m.group(1)) if m.group(1) else 32
        if not 1 <= size <= 64: raise DesignError('Width literal size must be between 1 and 64')
        number &= (1 << size) - 1
        if "'s" in m.group(0).lower() and number & (1 << (size-1)): number -= 1 << size
        return str(number)
    try:
        value = re.sub(r"(\d+)?'[sS]?([bBoOdDhH])([0-9a-fA-F_]+)", literal, value)
        value = value.replace('$clog2', 'clog2')
        tree = ast.parse(value, mode='eval')
        def visit(node, depth=0):
            if depth > 50: raise DesignError('Width expression is too complex')
            if isinstance(node, ast.Constant) and type(node.value) is int: result = node.value
            elif isinstance(node, ast.Name):
                if node.id in active or node.id not in params: raise DesignError(f'Undefined width parameter: {node.id}')
                result = integer_expr(params[node.id], params, (*active, node.id))
            elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub, ast.Invert)):
                x = visit(node.operand, depth+1)
                result = x if isinstance(node.op, ast.UAdd) else -x if isinstance(node.op, ast.USub) else ~x
            elif isinstance(node, ast.BinOp):
                a, b = visit(node.left, depth+1), visit(node.right, depth+1)
                if isinstance(node.op, (ast.LShift, ast.RShift, ast.Pow)) and not 0 <= b <= 64: raise DesignError('Exponent or shift is too large')
                ops = {ast.Add: lambda:a+b, ast.Sub:lambda:a-b, ast.Mult:lambda:a*b,
                       ast.Div:lambda:(abs(a)//abs(b)) * (-1 if (a<0) != (b<0) else 1),
                       ast.Mod:lambda:a-((abs(a)//abs(b)) * (-1 if (a<0) != (b<0) else 1))*b,
                       ast.LShift:lambda:a<<b, ast.RShift:lambda:a>>b, ast.BitAnd:lambda:a&b,
                       ast.BitOr:lambda:a|b, ast.BitXor:lambda:a^b, ast.Pow:lambda:a**b}
                if type(node.op) not in ops: raise DesignError('Unsupported width operation')
                result = ops[type(node.op)]()
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'clog2' and len(node.args) == 1 and not node.keywords:
                x = visit(node.args[0], depth+1)
                if x < 0: raise DesignError('$clog2 requires a nonnegative value')
                result = (x-1).bit_length() if x > 1 else 0
            else: raise DesignError(f'Unsupported width expression: {value}')
            if abs(result) > 2**63: raise DesignError('Width value is too large')
            return result
        return visit(tree.body)
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError, RecursionError) as exc:
        if isinstance(exc, DesignError): raise
        raise DesignError(f'Could not evaluate width: {value}') from exc

@dataclass
class Port:
    name: str
    span: str = ''
    signed: bool = False
    packed_extra: list[str] = field(default_factory=list)
    unpacked: list[str] = field(default_factory=list)
    two_state: bool = False

    @classmethod
    def parse(cls, text):
        """Editable port syntax: [type] [signed] [packed] name [unpacked]."""
        text=text.strip()
        m=re.fullmatch(r'(?P<prefix>(?:(?:wire|reg|logic|bit|var|signed|unsigned|byte|shortint|int|integer|longint|time)\b\s*)*)(?P<packed>(?:\[[^\[\]]+\]\s*)*)(?P<name>[A-Za-z_][A-Za-z0-9_$]*)(?P<unpacked>(?:\s*\[[^\[\]]+\])*)',text)
        if not m: raise DesignError(f'Unsupported port declaration: {text}')
        words=m['prefix'].split()
        types=[w for w in words if w in ('reg','logic','bit','byte','shortint','int','integer','longint','time')]
        if len(types)>1 or ('signed' in words and 'unsigned' in words): raise DesignError(f'Conflicting port type: {text}')
        base=types[0] if types else 'logic'
        packed=re.findall(r'\[([^\[\]]+)\]',m['packed'])
        unpacked=re.findall(r'\[([^\[\]]+)\]',m['unpacked'])
        integer_sizes={'byte':8,'shortint':16,'int':32,'integer':32,'longint':64,'time':64}
        if base in integer_sizes:
            if packed: raise DesignError('Additional packed ranges are not supported for integer types')
            packed=[f'{integer_sizes[base]-1}:0']
        for dim in packed:
            if ':' not in dim: raise DesignError('Packed range must have the form [7:0]')
        for i,dim in enumerate(unpacked):
            if ':' not in dim: unpacked[i]=f'0:({dim})-1'
        sign='signed' in words or (base in ('byte','shortint','int','integer','longint') and 'unsigned' not in words)
        return cls(identifier(m['name']),packed[0].strip() if packed else '',sign,
                   [d.strip() for d in packed[1:]],[d.strip() for d in unpacked],base in ('bit','byte','shortint','int','longint'))

    def dimensions_text(self,params=None):
        if params is not None:
            return (''.join(f'[{a}:{b}]' for a,b in self.packed_bounds(params)),
                    ''.join(f'[{a}:{b}]' for a,b in self.array_bounds(params)))
        compact=lambda d:re.sub(r'\s+','',d)
        return ''.join(f'[{compact(d)}]' for d in ([self.span] if self.span else [])+self.packed_extra), ''.join(f'[{compact(d)}]' for d in self.unpacked)

    def label(self):
        prefix=('bit ' if self.two_state else '')+('signed ' if self.signed else '')
        packed,unpacked=self.dimensions_text()
        return prefix+packed+self.name+unpacked

    @staticmethod
    def dimension(dim,params):
        # Split the range colon without confusing package scope or ternary expressions.
        parts=dim.split(':')
        if len(parts)!=2: raise DesignError(f'Range must have the form [msb:lsb]: [{dim}]')
        return tuple(integer_expr(p,params) for p in parts)

    def bounds(self, params):
        return self.dimension(self.span,params) if self.span else None

    def packed_bounds(self,params):
        return [self.dimension(d,params) for d in ([self.span] if self.span else [])+self.packed_extra]

    def array_bounds(self,params):
        return [self.dimension(d,params) for d in self.unpacked]

    def width(self, params):
        width=1
        for a,b in self.packed_bounds(params)+self.array_bounds(params): width*=abs(a-b)+1
        return width

    def declaration(self, params):
        packed=''.join(f'[{a}:{b}]' for a,b in self.packed_bounds(params))
        return ('signed ' if self.signed else '')+(packed+' ' if packed else '')

    def suffix(self,params):
        return ''.join(f' [{a}:{b}]' for a,b in self.array_bounds(params))

    def requires_sv(self):
        return self.two_state or bool(self.packed_extra or self.unpacked)

@dataclass
class Node:
    id: str = field(default_factory=uid)
    kind: str = 'module'
    module: str = 'my_module'
    name: str = 'u_module'
    x: int = 240
    y: int = 160
    w: int = 240
    h: int = 160
    inputs: list[Port] = field(default_factory=lambda:[Port('a')])
    outputs: list[Port] = field(default_factory=lambda:[Port('y')])
    params: dict[str, str] = field(default_factory=dict)

    transforms: dict[str, str] = field(default_factory=dict)
    hdl_source: str = ''

    def ports(self):
        return self.inputs + self.outputs

    def port(self, name):
        for p in self.ports():
            if p.name == name: return p
        raise DesignError(f'Port not found: {self.name}.{name}')

    def source(self, name):
        return any(p.name == name for p in self.outputs)

    def endpoint(self, name):
        side = self.outputs if self.source(name) else self.inputs
        index = next(i for i,p in enumerate(side) if p.name == name)
        return (self.x + self.w if self.source(name) else self.x, self.y + 60 + index*40)

    def minimum_size(self):
        ports_height=max(100,60+max(len(self.inputs),len(self.outputs))*40)
        return 160, ports_height+(40+20*len(self.params) if self.kind in ('module','inline') and self.params else 0)

    def parameters_y(self):
        return self.y+max(100,60+max(len(self.inputs),len(self.outputs))*40)

    def normalize(self):
        self.x, self.y = snap(self.x), snap(self.y)
        if self.kind in ('input','output'):
            self.w,self.h=240,100
            return
        minw,minh=self.minimum_size()
        self.w = max(minw, snap(self.w))
        self.h = max(minh, snap(self.h))

@dataclass
class Wire:
    id: str
    source: tuple[str,str] | None
    target: tuple[str,str] | None
    points: list[list[int]] = field(default_factory=list)
    end: list[int] | None = None
    join_wire: str | None = None
    join_position: float = 0.5
    vertices: list = field(default_factory=list)  # [stable ID, x, y]
    join_vertex: str | None = None
    start: list[int] | None = None  # explicit detached source position
    join_side: str | None = None   # preserves branch side after port removal
    width_hint: int = 1

    def branch_side(self):
        return self.join_side or ('start' if self.source is None else 'end')

    def loose_ends(self):
        result=[]
        if self.source is None and not (self.join_wire and self.branch_side()=='start'):
            result.append(('start',self.start if self.start is not None else self.end))
        if self.target is None and not (self.join_wire and self.branch_side()=='end'):
            result.append(('end',self.end))
        return result

    def set_loose(self,side,point):
        if side=='start':
            self.start=list(point)
            if self.target is not None:self.end=list(point)
        else:self.end=list(point)

    def endpoints(self):
        return [ep for ep in (self.source,self.target) if ep is not None]

@dataclass
class NetLabel:
    id: str
    name: str
    wire_id: str
    position: float = 0.5

@dataclass
class Net:
    wires: list[str]
    ports: list[tuple[str,str]]
    source: tuple[str,str] | None
    name: str = ''


@dataclass
class TextComment:
    id: str = field(default_factory=uid)
    text: str = 'Comment'
    x: int = 120
    y: int = 100
    w: int = 360
    font_size: int = 12
    h: int = 100
    kind: str = 'text'

    def validate(self):
        if self.kind not in ('text','group'): raise DesignError('Unknown comment type')
        if not isinstance(self.id,str) or not self.id: raise DesignError('Missing comment ID')
        if not isinstance(self.text,str) or not self.text.strip(): raise DesignError('Enter comment text')
        if len(self.text)>20000 or '\x00' in self.text: raise DesignError('Comment is too long or contains an invalid character')
        if any(type(v) is not int or abs(v)>COORD_LIMIT or v%GRID for v in (self.x,self.y)):
            raise DesignError('Comment coordinates must align to the 20-unit grid')
        limit=COORD_LIMIT if self.kind=='group' else 2000
        if type(self.w) is not int or not 100<=self.w<=limit or self.w%GRID: raise DesignError(f'Comment width: 100–{limit}, step 20')
        if type(self.h) is not int or not 40<=self.h<=limit or self.h%GRID: raise DesignError(f'Comment height: 40–{limit}, step 20')
        if type(self.font_size) is not int or not 8<=self.font_size<=32: raise DesignError('Font size: 8–32')


@dataclass
class Document:
    top: str = 'top'
    nodes: list[Node] = field(default_factory=list)
    wires: list[Wire] = field(default_factory=list)
    language: str = 'verilog'
    labels: list[NetLabel] = field(default_factory=list)
    comments: list[TextComment] = field(default_factory=list)

    declarations: str = ''
    export_path: str = ''

    def node(self, nid):
        for n in self.nodes:
            if n.id == nid: return n
        raise DesignError(f'Block not found: {nid}')

    def comment(self,comment_id):
        for comment in self.comments:
            if comment.id==comment_id: return comment
        raise DesignError('Comment not found')

    def module_groups(self):
        """Full containment; smallest frame wins overlaps (document order breaks ties)."""
        groups=[c for c in self.comments if c.kind=='group']
        result={}
        for n in self.nodes:
            matches=[c for c in groups if c.x<=n.x and c.y<=n.y and n.x+n.w<=c.x+c.w and n.y+n.h<=c.y+c.h]
            if matches: result[n.id]=min(matches,key=lambda c:c.w*c.h).id
        return result

    def comment_groups(self):
        groups=[c for c in self.comments if c.kind=='group']
        result={}
        for c in self.comments:
            if c.kind!='text': continue
            matches=[g for g in groups if g.x<=c.x and g.y<=c.y and c.x+c.w<=g.x+g.w and c.y+c.h<=g.y+g.h]
            if matches: result[c.id]=min(matches,key=lambda g:g.w*g.h).id
        return result

    def group_snapshot(self,group_id):
        members,wires=self.group_contents(group_id)
        comments={group_id}|{cid for cid,gid in self.comment_groups().items() if gid==group_id}
        return copy.deepcopy(dict(nodes=[n for n in self.nodes if n.id in members],
            comments=[c for c in self.comments if c.id in comments],
            wires=[w for w in self.wires if w.id in wires],
            labels=[l for l in self.labels if l.wire_id in wires],group_id=group_id))

    def paste_group(self,snapshot,dx=None,dy=0):
        data=copy.deepcopy(snapshot)
        if dx is None:
            frame=next(c for c in data['comments'] if c.id==data['group_id'])
            x=max([frame.x+frame.w]+[n.x+n.w for n in self.nodes]+[c.x+c.w for c in self.comments])+40
            dx=x-frame.x
        used={n.name for n in self.nodes}|{l.name for l in self.labels}|{self.top}
        used.update(re.findall(r'[A-Za-z_][A-Za-z0-9_$]*',self.declarations))
        def fresh(name):
            candidate=name;i=1
            while candidate in used: candidate=f'{name}_{i}';i+=1
            used.add(candidate);return candidate
        ids={o.id:uid() for key in ('nodes','comments','wires','labels') for o in data[key]}
        vertices={v[0]:uid() for w in data['wires'] for v in w.vertices}
        ports={};names={}
        for n in data['nodes']:
            old=n.name;n.name=fresh(old)
            if n.kind in ('input','output'): ports[n.id]=n.name;names[old]=n.name;n.ports()[0].name=n.name
        for label in data['labels']:
            if label.name not in names: names[label.name]=fresh(label.name)
            label.name=names[label.name];label.wire_id=ids[label.wire_id]
        # Keep references to cloned nets local; leave strings, comments and
        # hierarchical/package member names untouched.
        token=re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/|[A-Za-z_$][A-Za-z0-9_$]*',re.S)
        def rename_expression(value,shadowed):
            def replace(match):
                name=match.group();prefix=value[:match.start()].rstrip()
                if name in shadowed or prefix.endswith(('.', '::')): return name
                return names.get(name,name)
            return token.sub(replace,value)
        for n in data['nodes']:
            n.transforms={key:rename_expression(value,set(n.params)) for key,value in n.transforms.items()}
        for w in data['wires']:
            for attr in ('source','target'):
                ep=getattr(w,attr)
                if ep: setattr(w,attr,(ids[ep[0]],ports.get(ep[0],ep[1])))
            w.join_wire=ids.get(w.join_wire);w.join_vertex=vertices.get(w.join_vertex)
            w.vertices=[[vertices[k],x+dx,y+dy] for k,x,y in w.vertices]
            w.points=[[x+dx,y+dy] for x,y in w.points]
            if w.end: w.end=[w.end[0]+dx,w.end[1]+dy]
            if w.start: w.start=[w.start[0]+dx,w.start[1]+dy]
        for key in ('nodes','comments'):
            for obj in data[key]: obj.x+=dx;obj.y+=dy
        for key in ('nodes','comments','wires','labels'):
            for obj in data[key]: obj.id=ids[obj.id]
        trial=copy.deepcopy(self)
        for key in ('nodes','comments','wires','labels'): getattr(trial,key).extend(data[key])
        trial.validate(electrical=False)
        for key in ('nodes','comments','wires','labels'): getattr(self,key).extend(data[key])
        return ids[data['group_id']]

    def group_contents(self,group_id):
        members={nid for nid,gid in self.module_groups().items() if gid==group_id}
        return members,self.internal_wires(members)

    def internal_wires(self,members):
        wires={w.id for w in self.wires if w.endpoints() and all(ep[0] in members for ep in w.endpoints())}
        # A branch is internal only if its host is also internal.
        while True:
            keep={wid for wid in wires if not self.wire(wid).join_wire or self.wire(wid).join_wire in wires}
            if keep==wires: break
            wires=keep
        return wires

    def move_group(self,group_id,dx,dy,contents=None,comments=None):
        members,wires=contents if contents is not None else self.group_contents(group_id)
        self.move_objects(members,comments if comments is not None else {group_id}|{cid for cid,gid in self.comment_groups().items() if gid==group_id},wires,dx,dy)

    def move_objects(self,members,comments,wires,dx,dy):
        for comment in self.comments:
            if comment.id in comments: comment.x+=dx;comment.y+=dy
        for n in self.nodes:
            if n.id in members: n.x+=dx;n.y+=dy
        for w in self.wires:
            if w.id not in wires: continue
            w.points=[[x+dx,y+dy] for x,y in w.points]
            w.vertices=[[key,x+dx,y+dy] for key,x,y in w.vertices]
            if w.end: w.end=[w.end[0]+dx,w.end[1]+dy]
            if w.start: w.start=[w.start[0]+dx,w.start[1]+dy]

    def floating_wires(self,wire_id):
        """Physical wire component with no attached ports; labels do not join motion."""
        component={wire_id}
        while True:
            expanded=component|{w.id for w in self.wires if w.join_wire in component}
            expanded.update(w.join_wire for w in self.wires if w.id in component and w.join_wire)
            if expanded==component:break
            component=expanded
        return component if all(not self.wire(wid).endpoints() for wid in component) else set()

    def resolve(self, ep):
        n = self.node(ep[0])
        return n, n.port(ep[1])

    def validate(self,electrical=True):
        identifier(self.top)
        if not isinstance(self.export_path,str) or '\x00' in self.export_path: raise DesignError('Invalid export path')
        if self.language not in ('verilog','systemverilog'): raise DesignError('Unknown export language')
        if not isinstance(self.declarations,str) or '\x00' in self.declarations: raise DesignError('Invalid top-level declarations text')
        ids, names = set(), set()
        for n in self.nodes:
            if not isinstance(n.id,str) or not n.id or n.id in ids: raise DesignError('Duplicate or empty block ID')
            ids.add(n.id)
            if n.kind not in ('module','inline','input','output'): raise DesignError('Unknown block type')
            identifier(n.name)
            if n.name in names: raise DesignError(f'Duplicate name: {n.name}')
            names.add(n.name)
            if n.kind == 'module':
                identifier(n.module)
                if n.module == self.top: raise DesignError('Child module name matches the top module')
            elif n.kind=='inline':
                from inline_hdl import parse_inline
                parsed=parse_inline(n.hdl_source)
                if n.inputs!=parsed.inputs or n.outputs!=parsed.outputs or n.params!=parsed.params:
                    raise DesignError(f'Inline HDL interface does not match the source: {n.name}')
                if n.transforms: raise DesignError('Inline HDL uses its source text instead of input transforms')
            elif len(n.ports()) != 1 or (n.kind == 'input' and n.inputs) or (n.kind == 'output' and n.outputs) or n.ports()[0].name != n.name or n.params:
                raise DesignError('Invalid top-level port structure')
            if not isinstance(n.transforms,dict): raise DesignError('Invalid port transforms')
            for key,value in n.transforms.items():
                if n.kind in ('input','output') or key not in {p.name for p in n.inputs}: raise DesignError('Transforms are available only for module inputs: '+str(key))
                transform_expression(value)
            for k,v in n.params.items(): identifier(k); parameter_value(k,n.params)
            pn = set()
            for p in n.ports():
                identifier(p.name)
                if type(p.signed) is not bool or type(p.two_state) is not bool: raise DesignError('Invalid port flag type')
                if p.packed_extra and not p.span: raise DesignError('Missing first packed dimension')
                if p.name in pn: raise DesignError(f'Duplicate port: {n.name}.{p.name}')
                pn.add(p.name)
                if p.width(n.params) > 1048576: raise DesignError('Bus width cannot exceed 1048576 bits')
            for v in [n.x,n.y,n.w,n.h]:
                if type(v) is not int or abs(v)>COORD_LIMIT or v % GRID: raise DesignError('Coordinates and dimensions must align to the 20-unit grid and be within ±100 000 000')
            if n.w < 160 or n.h < max(100,60+max(len(n.inputs),len(n.outputs))*40): raise DesignError('Frame is too small for the ports')
        wire_ids=set()
        def gridpoint(point):
            if not isinstance(point,(list,tuple)) or len(point)!=2 or any(type(v) is not int or abs(v)>COORD_LIMIT or v%GRID for v in point):
                raise DesignError('Wire points must align to the grid')
        for w in self.wires:
            if not isinstance(w.id,str) or not w.id or w.id in wire_ids: raise DesignError('Duplicate or empty wire ID')
            wire_ids.add(w.id)
            if not w.endpoints() and not w.vertices: raise DesignError('Detached wire has no geometry')
            for ep in w.endpoints():
                if not isinstance(ep,(list,tuple)) or len(ep)!=2: raise DesignError('Invalid port reference')
                self.resolve(ep)
            for side,point in w.loose_ends(): gridpoint(point)
            if w.start is not None:gridpoint(w.start)
            if w.join_side not in (None,'start','end'):raise DesignError('Invalid branch side')
            if type(w.width_hint) is not int or w.width_hint<1:raise DesignError('Invalid wire width hint')
            for point in w.points: gridpoint(point)
        for w in self.wires:
            vertex_ids=set()
            for vertex in w.vertices:
                if not isinstance(vertex,list) or len(vertex)!=3 or not isinstance(vertex[0],str) or not vertex[0] or vertex[0] in vertex_ids: raise DesignError('Invalid or duplicate wire vertex')
                vertex_ids.add(vertex[0]);gridpoint(vertex[1:])
            if w.vertices and len(w.vertices)<2: raise DesignError('A wire needs at least two vertices')
            if w.join_vertex is not None and (not w.join_wire or w.join_vertex not in {v[0] for v in self.wire(w.join_wire).vertices}): raise DesignError('Missing junction vertex')
            if w.join_wire is not None:
                if w.join_wire not in wire_ids or (w.source if w.branch_side()=='start' else w.target) is not None: raise DesignError('Invalid wire branch')
                if type(w.join_position) not in (int,float) or not math.isfinite(w.join_position) or not 0<=w.join_position<=1: raise DesignError('Invalid branch position')
                seen={w.id};current=w
                while current.join_wire is not None:
                    if current.join_wire in seen: raise DesignError('Circular wire attachment')
                    seen.add(current.join_wire);current=self.wire(current.join_wire)
                    if len(seen)>128: raise DesignError('Too many nested branches (limit: 128)')
        label_ids=set()
        for label in self.labels:
            identifier(label.name)
            if not label.id or label.id in label_ids: raise DesignError('Duplicate label ID')
            label_ids.add(label.id)
            if label.wire_id not in wire_ids: raise DesignError('Label refers to a deleted wire')
            if type(label.position) not in (int,float) or not math.isfinite(label.position) or not 0<=label.position<=1:
                raise DesignError('Invalid label position on wire')
        comment_ids=set()
        for comment in self.comments:
            comment.validate()
            if comment.id in comment_ids: raise DesignError('Duplicate comment ID')
            comment_ids.add(comment.id)
        if electrical:self.nets()

    def wire(self,wire_id):
        for w in self.wires:
            if w.id==wire_id: return w
        raise DesignError('Wire not found')

    def nets(self,strict=True,issues=None):
        """Electrical connectivity is defined by shared ports and equal net labels.

        Geometry, crossed segments, and coincident loose ends do NOT connect nets.
        Undriven partial components may be saved, but cannot be exported.
        """
        issues=[] if issues is None else issues
        def report(message,endpoints,wires,fatal=True):
            issues.append(dict(message=message,ports=list(endpoints),wires=[w.id for w in wires]))
            if strict and fatal:raise DesignError(message)
        parent={w.id:w.id for w in self.wires}
        def root(key):
            while parent[key]!=key:
                parent[key]=parent[parent[key]]; key=parent[key]
            return key
        def union(a,b):
            a,b=root(a),root(b)
            if a!=b: parent[b]=a
        ports={}; labels={}
        for w in self.wires:
            for ep in w.endpoints():
                ep=tuple(ep)
                if ep in ports: union(w.id,ports[ep])
                else: ports[ep]=w.id
        for w in self.wires:
            if w.join_wire is not None: union(w.id,w.join_wire)
        top_ports={n.name:(n.id,n.name) for n in self.nodes if n.kind in ('input','output')}
        for label in self.labels:
            if label.wire_id not in parent: raise DesignError('Label refers to a deleted wire')
            if label.name in labels: union(label.wire_id,labels[label.name])
            else: labels[label.name]=label.wire_id
            ep=top_ports.get(label.name)
            if ep in ports: union(label.wire_id,ports[ep])
        groups={}
        for w in self.wires: groups.setdefault(root(w.id),[]).append(w)
        label_names={}
        for label in self.labels: label_names.setdefault(root(label.wire_id),set()).add(label.name)
        result=[]
        for key,wires in groups.items():
            endpoints=list(dict.fromkeys(tuple(ep) for w in wires for ep in w.endpoints()))
            for label_name in label_names.get(key,set()):
                ep=top_ports.get(label_name)
                if ep and ep not in endpoints: endpoints.append(ep)
            drivers=[ep for ep in endpoints if self.node(ep[0]).source(ep[1])]
            if len(drivers)>1:
                names=', '.join(f'{self.node(ep[0]).name}.{ep[1]}' for ep in drivers)
                report('Multiple drivers on one net: '+names,drivers,wires)
            names=label_names.get(key,set())
            if len(names)>1: report('Conflicting label names on one net: '+', '.join(sorted(names)),endpoints,wires)
            name=next(iter(names),'')
            source=drivers[0] if drivers else None
            direct=[ep for ep in endpoints if ep[1] not in self.node(ep[0]).transforms]
            if not direct: direct=endpoints[:1]
            for wire in wires:
                for attr,expected in (('source',True),('target',False)):
                    ep=getattr(wire,attr)
                    if ep and self.node(ep[0]).source(ep[1])!=expected:
                        report(f'Port direction mismatch: {self.node(ep[0]).name}.{ep[1]} is not an {"output" if expected else "input"}',[ep],[wire])
            if not endpoints:
                result.append(Net([w.id for w in wires],[],None,name));continue
            a,ap=self.resolve(source or direct[0])
            for ep in endpoints:
                if ep[1] in self.node(ep[0]).transforms: continue
                b,bp=self.resolve(ep)
                if ap.array_bounds(a.params)!=bp.array_bounds(b.params):
                    report(f'Unpacked dimension mismatch on net {name or 'unnamed'}: {a.name}.{ap.name} → {b.name}.{bp.name}',[source or direct[0],ep],wires)
                if ap.width(a.params)!=bp.width(b.params):
                    report(f'Width mismatch: {a.name}.{ap.name} ({ap.width(a.params)}) → {b.name}.{bp.name} ({bp.width(b.params)})',[source or direct[0],ep],wires)
                if ap.signed!=bp.signed:
                    report(f'Signedness mismatch: {a.name}.{ap.name} ({"signed" if ap.signed else "unsigned"}) → {b.name}.{bp.name} ({"signed" if bp.signed else "unsigned"})',[source or direct[0],ep],wires,fatal=False)
            if name:
                if name==self.top: report('Label matches the top module name',endpoints,wires)
                for n in self.nodes:
                    if n.name==name and (n.kind in ('module','inline') or (n.id,n.name) not in endpoints):
                        report(f'Label name {name} is used by an instance or another top-level port',endpoints,wires)
            result.append(Net([w.id for w in wires],endpoints,source,name))
        return result

    def connect(self, first, second=None, points=None, end=None, replace_id=None, join_wire=None, join_position=0.5,allow_invalid=False,drawn_path=None):
        original_first=tuple(first)
        a,_=self.resolve(first); points=copy.deepcopy(points or [])
        if second is not None:
            b,_=self.resolve(second)
            if not allow_invalid and a.source(first[1])==b.source(second[1]): raise DesignError('Connect an output to an input')
            if not a.source(first[1]): first,second=second,first; points.reverse()
            source,target=tuple(first),tuple(second); end=None
        elif a.source(first[1]): source,target=tuple(first),None
        else: source,target=None,tuple(first); points.reverse()
        w=Wire(replace_id or uid(),source,target,points,list(end) if end is not None else None,join_wire,join_position)
        originals=self.wires[:];before=copy.deepcopy(self.wires)
        if replace_id:
            old=self.wire(replace_id); self.wires[self.wires.index(old)]=w
        else: self.wires.append(w)
        try:
            if join_wire: self.attach_vertex(w,join_position)
            if drawn_path is not None:
                path=list(drawn_path)
                if w.target==original_first:path.reverse()
                w.vertices=[[uid(),int(x),int(y)] for x,y in path]
            self.freeze_wire(w)
            connected_node,connected_port=self.resolve(original_first);w.width_hint=connected_port.width(connected_node.params)
            for child in self.wires:
                if child.join_wire==w.id:
                    child.join_vertex=None;self.attach_vertex(child,child.join_position)
            self.validate(electrical=not allow_invalid)
        except Exception:
            for original,snapshot in zip(originals,before):
                original.__dict__.clear();original.__dict__.update(copy.deepcopy(snapshot.__dict__))
            self.wires=originals
            raise
        return w

    def freeze_wire(self,wire):
        wire.vertices=[[key or uid(),int(x),int(y)] for key,(x,y) in wire_path(self,wire)]

    def attach_vertex(self,wire,position):
        host=self.wire(wire.join_wire)
        if host.id==wire.id: raise DesignError('Cannot attach a wire to itself')
        # Check dependency cycles before evaluating geometry.
        seen={wire.id};current=host
        while True:
            if current.id in seen: raise DesignError('Circular wire attachment')
            seen.add(current.id)
            if not current.join_wire: break
            current=self.wire(current.join_wire)
        self.freeze_wire(host)
        x,y=path_position(route(self,host),position);x,y=snap(x),snap(y)
        for key,vx,vy in host.vertices:
            if (vx,vy)==(x,y): wire.join_vertex=key;break
        else:
            index=nearest_segment(route(self,host),x,y)
            key=uid();host.vertices.insert(index+1,[key,x,y]);wire.join_vertex=key
        wire.join_position=project_to_path(route(self,host),x,y)[0]
        if wire.branch_side()=='end' or wire.target is not None:wire.end=[x,y]

    def move_junction(self,wire,x,y):
        if not wire.join_vertex: self.attach_vertex(wire,wire.join_position)
        host=self.wire(wire.join_wire);self.freeze_wire(host)
        pos,_=project_to_path(route(self,host),snap(x),snap(y))
        px,py=path_position(route(self,host),pos)
        for vertex in host.vertices:
            if vertex[0]==wire.join_vertex: vertex[1:]=[snap(px),snap(py)];break
        wire.join_position=pos
        self.normalize_branches(wire.id)

    def reset_wire_route(self,wire):
        if not wire.endpoints():return
        children=[w for w in self.wires if w.join_wire==wire.id]
        for child in children:
            child.join_position=project_to_path(route(self,wire),*junction_point(self,child))[0]
            child.join_vertex=None
        wire.points=[];wire.vertices=[];self.freeze_wire(wire)
        for child in children:self.attach_vertex(child,child.join_position)

    def consumed_tips(self):
        joined={(w.join_wire,junction_point(self,w)) for w in self.wires if w.join_wire}
        return [(w.id,side) for w in self.wires for side,p in w.loose_ends() if (w.id,tuple(p)) in joined]

    def trim_consumed_tips(self,tips):
        for wid,side in tips:
            host=self.wire(wid);children=[w for w in self.wires if w.join_wire==wid]
            if not children:continue
            self.freeze_wire(host)
            keys={w.join_vertex for w in children}
            indices=[i for i,v in enumerate(host.vertices) if v[0] in keys]
            if not indices:continue
            cut=min(indices) if side=='start' else max(indices)
            host.vertices=host.vertices[cut:] if side=='start' else host.vertices[:cut+1]
            point=host.vertices[0 if side=='start' else -1][1:];host.set_loose(side,point)
            if len(host.vertices)==1:host.vertices.append([uid(),*point])

    def remove_free_segment(self,wire_id,index):
        """Remove a selected terminal edge, retaining the rest of the conductor."""
        wire=self.wire(wire_id);self.freeze_wire(wire)
        if not 0<=index<len(wire.vertices)-1:return False
        occupied={junction_point(self,w) for w in self.wires if w.join_wire==wire_id}
        side=next((side for side,p in wire.loose_ends()
                   if tuple(p) not in occupied and ((side=='start' and index==0) or (side=='end' and index==len(wire.vertices)-2))),None)
        if side is None:return False
        if len(wire.vertices)==2:self.remove_wire(wire_id);return True
        wire.vertices=wire.vertices[1:] if side=='start' else wire.vertices[:-1]
        wire.set_loose(side,wire.vertices[0 if side=='start' else -1][1:]);wire.points=[]
        return True

    def move_segment(self,wire,index,dx,dy,original):
        """Move one edge between consecutive corners/junctions, not a whole run."""
        if wire.join_wire and wire.join_vertex not in {v[0] for v in self.wire(wire.join_wire).vertices}:
            point=original[0 if wire.branch_side()=='start' else -1][1:]
            self.attach_vertex(wire,project_to_path(route(self,self.wire(wire.join_wire)),*point)[0])
        consumed=self.consumed_tips()
        a,b=original[index:index+2];axis=2 if a[2]==b[2] else 1
        offset=dy if axis==2 else dx
        wire.vertices=copy.deepcopy(original)
        if not offset:
            if wire.join_wire and wire.join_vertex not in {v[0] for v in self.wire(wire.join_wire).vertices}:
                point=original[0 if wire.branch_side()=='start' else -1][1:]
                self.attach_vertex(wire,project_to_path(route(self,self.wire(wire.join_wire)),*point)[0])
            return
        result=[]
        for at,vertex in enumerate(original):
            point=vertex.copy()
            if at not in (index,index+1):result.append(point);continue
            moved=point.copy();moved[axis]+=offset
            joined=wire.join_wire and ((at==0 and wire.branch_side()=='start') or (at==len(original)-1 and wire.branch_side()=='end'))
            if joined:
                host=self.wire(wire.join_wire);old_joint=junction_point(self,wire)
                # Other arms attached to this terminal belong to the same
                # physical node, not to the moving arm. Reparent them first.
                for child in list(self.wires):
                    if child.join_wire==wire.id and junction_point(self,child)==old_joint:
                        self.freeze_wire(child);child.join_wire=host.id;child.join_vertex=None
                        self.attach_vertex(child,project_to_path(route(self,host),*old_joint)[0])
                host_path=route(self,host);pos,distance=project_to_path(host_path,*moved[1:])
                if distance:
                    projected=path_position(host_path,pos)
                    side=next((side for side,p in host.loose_ends() if tuple(p)==tuple(projected)),None)
                    if side is not None:
                        self.freeze_wire(host)
                        vertex=[uid(),*moved[1:]]
                        if side=='start':host.vertices.insert(0,vertex)
                        else:host.vertices.append(vertex)
                        host.set_loose(side,moved[1:]);pos=0.0 if side=='start' else 1.0
                self.attach_vertex(wire,pos)
                moved[1:]=junction_point(self,wire);result.append(moved)
            elif at==0 and wire.source:
                moved[0]=uid();result.extend([point,moved])
            elif at==len(original)-1 and wire.target:
                moved[0]=uid();result.extend([moved,point])
            elif at==index and at>0 and original[at-1][axis]==point[axis]:
                moved[0]=uid();result.extend([point,moved])
            elif at==index+1 and at+1<len(original) and original[at+1][axis]==point[axis]:
                moved[0]=uid();result.extend([moved,point])
            else:
                result.append(moved)
                if at==0:wire.set_loose('start',moved[1:])
                elif at==len(original)-1:wire.set_loose('end',moved[1:])
        wire.vertices=result
        self.trim_consumed_tips(consumed)
        self.normalize_branches(wire.id)

    def normalize_branches(self,wire_id):
        """Store shared prefixes once and place each dot at actual divergence.

        Only explicitly connected hosts/branches participate. An unrelated
        geometric crossing never becomes an electrical connection.
        """
        root=self.wire(wire_id)
        while root.join_wire:root=self.wire(root.join_wire)
        ordered=[]
        def visit(w):
            ordered.append(w)
            for child in self.wires:
                if child.join_wire==w.id:visit(child)
        visit(root)
        for branch in ordered[1:]:
            host=self.wire(branch.join_wire);self.freeze_wire(host);self.freeze_wire(branch)
            reverse=branch.branch_side()=='end'
            path=list(reversed(branch.vertices)) if reverse else list(branch.vertices)
            host_points=route(self,host);last=tuple(path[0][1:]);cut=0
            for i,(a,b) in enumerate(zip(path,path[1:])):
                p,q=tuple(a[1:]),tuple(b[1:])
                if p==q:cut=i+1;continue
                axis=0 if p[1]==q[1] else 1;other=1-axis;sign=1 if q[axis]>p[axis] else -1
                intervals=[]
                for h,k in zip(host_points,host_points[1:]):
                    if h[other]==k[other]==p[other]:intervals.append(sorted((h[axis],k[axis])))
                reach=p[axis]
                while True:
                    candidates=[hi if sign>0 else lo for lo,hi in intervals if lo<=reach<=hi]
                    nxt=(max(candidates) if sign>0 else min(candidates)) if candidates else reach
                    if nxt==reach:break
                    reach=nxt
                reach=min(reach,q[axis]) if sign>0 else max(reach,q[axis])
                if reach==p[axis]:break
                last=list(p);last[axis]=reach;last=tuple(last)
                cut=i+1 if last==q else i
                if last!=q:break
            if last==tuple(path[0][1:]):continue
            # Descendants attached to the removed prefix attach directly to the
            # host instead; save their physical junction before cutting it.
            children=[(w,junction_point(self,w)) for w in self.wires if w.join_wire==branch.id]
            position=project_to_path(host_points,*last)[0];self.attach_vertex(branch,position)
            tail=path[cut:]
            if tuple(tail[0][1:])!=last:tail=[[uid(),*last]]+tail[1:]
            if len(tail)<2:tail=tail+[[uid(),*last]]
            branch.vertices=list(reversed(tail)) if reverse else tail
            for child,point in children:
                if project_to_path(route(self,branch),*point)[1]>0:
                    child.join_wire=host.id;child.join_vertex=None
                    self.attach_vertex(child,project_to_path(route(self,host),*point)[0])
        for w in ordered:self.freeze_wire(w)

    def label_wire(self,wire_id,name,position=0.5,allow_invalid=False):
        self.wire(wire_id); identifier(name)
        before=copy.deepcopy(self.labels)
        label=next((l for l in self.labels if l.wire_id==wire_id),None)
        if label: label.name=name; label.position=position
        else: label=NetLabel(uid(),name,wire_id,position); self.labels.append(label)
        try: self.validate(electrical=not allow_invalid)
        except Exception: self.labels=before; raise
        return label

    def remove_wire(self,wire_id):
        # Keep attached branches as dangling wires at their current positions.
        attached=[(w,junction_point(self,w)) for w in self.wires if w.join_wire==wire_id]
        for w,point in attached:
            side=w.branch_side();w.join_wire=None;w.join_vertex=None;w.join_side=None;w.set_loose(side,point)
        self.wires=[w for w in self.wires if w.id!=wire_id]
        self.labels=[l for l in self.labels if l.wire_id!=wire_id]

    def detach_port(self,endpoint):
        # Freeze before removing references so shape and shared vertex IDs survive.
        affected=[w for w in self.wires if endpoint in w.endpoints()]
        for w in affected:self.freeze_wire(w)
        node,port=self.resolve(endpoint);point=node.endpoint(port.name)
        for w in affected:
            # A target-only stub stores its free source position in `end`.
            # Make that position explicit before `end` becomes the newly
            # detached target; otherwise both ends collapse onto the port.
            for side,free_point in w.loose_ends():w.set_loose(side,free_point)
            w.width_hint=port.width(node.params)
            if w.join_wire:w.join_side=w.branch_side()
            for attr,side in (('source','start'),('target','end')):
                if getattr(w,attr)==endpoint:
                    setattr(w,attr,None);w.set_loose(side,point)

    def remove_node(self,node_id):
        for port in self.node(node_id).ports():self.detach_port((node_id,port.name))
        self.nodes=[n for n in self.nodes if n.id!=node_id]

    def attach_coincident(self,node_ids=None,wire_ids=None):
        """Attach only unambiguous exact coincidences after a completed edit."""
        positions={}
        for n in self.nodes:
            for p in n.ports():positions.setdefault(n.endpoint(p.name),[]).append((n.id,p.name))
        candidates=[]
        for w in self.wires:
            for side,point in w.loose_ends():
                ports=positions.get(tuple(point),[])
                if len(ports)!=1:continue
                ep=ports[0]
                if node_ids is not None and ep[0] not in node_ids and (wire_ids is None or w.id not in wire_ids):continue
                candidates.append((w,side,ep))
        for w,side,ep in candidates:
            self.freeze_wire(w)
            setattr(w,'source' if side=='start' else 'target',ep)
            if side=='start':w.start=None
            if w.source and w.target:w.end=None
        return len(candidates)

    def connection_issues(self):
        issues=[];self.nets(strict=False,issues=issues);return issues

    def serialize(self):
        return {'format':'VerilogCanvas','version':12,'language':self.language,'top':self.top,'nodes':[asdict(n) for n in self.nodes],'wires':[asdict(w) for w in self.wires],'labels':[asdict(l) for l in self.labels],'comments':[asdict(c) for c in self.comments],'declarations':self.declarations,'export_path':self.export_path}

    @classmethod
    def deserialize(cls, data):
        try:
            if data['format'] != 'VerilogCanvas' or data['version'] not in (1,2,3,4,5,6,7,8,9,10,11,12): raise DesignError('Unknown schematic format or version')
            nodes=[]
            for entry in data['nodes']:
                d=copy.deepcopy(entry)
                d['inputs']=[Port(**p) for p in d['inputs']]; d['outputs']=[Port(**p) for p in d['outputs']]
                n=Node(**d)
                if data['version']<3 or n.kind in ('input','output'): n.normalize()
                nodes.append(n)
            wires=[Wire(w['id'],tuple(w['source']) if w['source'] is not None else None,tuple(w['target']) if w['target'] is not None else None,w['points'],w.get('end'),w.get('join_wire'),w.get('join_position',0.5),w.get('vertices',[]),w.get('join_vertex'),w.get('start'),w.get('join_side'),w.get('width_hint',1)) for w in data['wires']]
            labels=[NetLabel(**l) for l in data.get('labels',[])]
            comments=[TextComment(**c) for c in data.get('comments',[])]
            doc=cls(data['top'],nodes,wires,data.get('language','verilog'),labels,comments,data.get('declarations',''),data.get('export_path','')); doc.validate(electrical=False)
            for wire in doc.wires:
                if not wire.vertices: doc.freeze_wire(wire)
            for wire in doc.wires:
                if wire.join_wire and not wire.join_vertex: doc.attach_vertex(wire,wire.join_position)
            doc.validate(electrical=False);return doc
        except (KeyError, TypeError, AttributeError, ValueError, RecursionError) as exc:
            if isinstance(exc, DesignError): raise
            raise DesignError(f'Corrupt schematic file: {exc}') from exc

    def save(self, path):
        self.validate(electrical=False)
        from schematic_text import encode_document
        path=Path(path); temporary=path.with_name(path.name+'.tmp')
        temporary.write_bytes(encode_document(self))
        if path.exists(): shutil.copy2(path,path.with_name(path.name+'.bak'))
        temporary.replace(path)

    @classmethod
    def load(cls, path):
        from schematic_text import decode_document
        if Path(path).stat().st_size > 20*1024*1024: raise DesignError('Schematic file exceeds 20 MB')
        return cls.deserialize(decode_document(Path(path).read_bytes()))

    def verilog(self, language=None):
        self.validate()
        language=language or self.language
        if language not in ('verilog','systemverilog'): raise DesignError('Export language must be verilog or systemverilog')
        sv=language=='systemverilog'
        if not sv and any(p.requires_sv() for n in self.nodes for p in n.ports()):
            raise DesignError('The schematic contains bit or multidimensional/array ports. Select SystemVerilog (.sv).')
        def dtype(p): return ('bit' if p.two_state else 'logic') if sv else 'wire'
        from inline_hdl import flat_types, flat_context, declared_signals, parse_inline
        inline_types=flat_types(self)
        user_signals=set(declared_signals(self.declarations)) if any(n.kind=='inline' for n in self.nodes) else set()
        for n in self.nodes:
            if n.kind=='inline': user_signals.update(declared_signals(parse_inline(n.hdl_source).body))
        def signal_type(name,p): return inline_types.get(name,dtype(p))

        components=self.nets()
        connected={ep for net in components if net.source for ep in net.ports}
        missing=[f'{n.name}.{p.name}' for n in self.nodes for p in n.inputs if (n.id,p.name) not in connected]
        if missing: raise DesignError('Module inputs or top-level outputs have no driver:\n'+ '\n'.join(missing))
        top_ports=[n for n in self.nodes if n.kind in ('input','output')]
        lines=[f'// Generated by VerilogCanvas. {"SystemVerilog" if sv else "Verilog-2001"}.','// Child module implementations must be supplied separately.',f'module {self.top} (']
        lines += [f'    {n.kind} {signal_type(n.name,n.ports()[0]) if n.kind=='output' else dtype(n.ports()[0])} {n.ports()[0].declaration({})}{n.name}{n.ports()[0].suffix({})}'+(',' if i<len(top_ports)-1 else '') for i,n in enumerate(top_ports)]
        lines += [');','']
        if self.declarations.strip(): lines += [self.declarations.rstrip(),'']
        used={n.name for n in self.nodes}|{self.top}|{net.name for net in components if net.name}
        # Reserve names appearing in user HDL to avoid generated-net collisions.
        used.update(re.findall(r'[A-Za-z_][A-Za-z0-9_$]*',self.declarations))
        for n in self.nodes:
            if n.kind=='inline': used.update(re.findall(r'[A-Za-z_][A-Za-z0-9_$]*',n.hdl_source))
        nets={}; counter=0; assigned=[]
        groups=self.module_groups(); grouped_declarations={}
        referenced={n.id:set(re.findall(r'[A-Za-z_][A-Za-z0-9_$]*',' '.join(n.transforms.values())+' '+' '.join(n.params.values())+' '+n.hdl_source)) for n in self.nodes if n.kind in ('module','inline')}
        top_references=set(re.findall(r'[A-Za-z_][A-Za-z0-9_$]*',self.declarations))
        top_names={n.name for n in top_ports}
        for net in components:
            if net.source is None: raise DesignError('Net '+(net.name or 'unnamed')+' has no driver')
            name=net.name
            if not name:
                ports=[self.node(ep[0]) for ep in net.ports if self.node(ep[0]).kind in ('input','output')]
                if ports: name=next((n.name for n in ports if n.kind=='input'),ports[0].name)
            if not name:
                inline_ports=[ep for ep in net.ports if self.node(ep[0]).kind=='inline']
                if inline_ports: name=next((ep[1] for ep in inline_ports if self.node(ep[0]).source(ep[1])),inline_ports[0][1])
            if not name:
                while f'syn_net_{counter}' in used: counter+=1
                name=f'syn_net_{counter}'; used.add(name); counter+=1
            a,ap=self.resolve(net.source)
            if name not in top_names and name not in user_signals:
                owners={groups.get(ep[0]) for ep in net.ports}
                owners.update(groups.get(nid) for nid,refs in referenced.items() if name in refs)
                if name in top_references or any(self.node(ep[0]).kind in ('input','output') for ep in net.ports): owners.add(None)
                owner=next(iter(owners)) if len(owners)==1 else None
                grouped_declarations.setdefault(owner,[]).append(f'{signal_type(name,ap)} {ap.declaration(a.params)}{name}{ap.suffix(a.params)};')
            for ep in net.ports: nets[ep]=name
            assigned.append((net,name))
        flat_lines,_=flat_context(self,components,nets,sv)
        lines.extend(grouped_declarations.get(None,[]));lines.extend(flat_lines)
        if assigned: lines.append('')
        for net,name in assigned:
            n,p=self.resolve(net.source)
            if n.kind=='input' and name!=n.name: lines.append(f'assign {name} = {n.name};')
            for ep in net.ports:
                n,p=self.resolve(ep)
                if n.kind=='output' and n.name!=name: lines.append(f'assign {n.name} = {name};')
        lines.append('')
        modules=[n for n in self.nodes if n.kind in ('module','inline')]
        ordered=[];seen=set()
        for n in modules:
            gid=groups.get(n.id)
            if gid is None: ordered.append(n)
            elif gid not in seen:
                seen.add(gid);ordered.extend(m for m in modules if groups.get(m.id)==gid)
        emitted=set()
        for n in ordered:
            gid=groups.get(n.id)
            if gid is not None and gid not in emitted:
                emitted.add(gid)
                # One // line per user line: multiline text cannot inject HDL.
                lines.extend('// ############ '+line+' #############' for line in self.comment(gid).text.splitlines())
                lines.extend(grouped_declarations.get(gid,[]));lines.append('')
            if n.kind=='inline':
                from inline_hdl import export_inline
                lines.extend(export_inline(n,nets,used,sv));continue
            lines.append(n.module)
            if n.params:
                lines.append('#(')
                lines.extend(f'    .{k}({parameter_value(k,n.params)})'+(',' if i<len(n.params)-1 else '') for i,(k,v) in enumerate(n.params.items()))
                lines.append(')')
            lines.extend([n.name,'('])
            for i,p in enumerate(n.ports()):
                net=nets.get((n.id,p.name),'')
                if p.name in n.transforms: net=transform_expression(n.transforms[p.name],net)
                lines.append(f'    .{p.name}({net})'+(',' if i<len(n.ports())-1 else ''))
            lines += [');','']
        lines += ['endmodule','']
        return '\n'.join(lines)

def junction_point(doc,wire):
    if wire.join_vertex:
        for key,point in wire_path(doc,doc.wire(wire.join_wire)):
            if key==wire.join_vertex: return point
        raise DesignError('Missing junction vertex')
    point=path_position(route(doc,doc.wire(wire.join_wire)),wire.join_position)
    return snap(point[0]),snap(point[1])

def wire_terminals(doc,wire):
    joint=junction_point(doc,wire) if wire.join_wire else None
    a=doc.node(wire.source[0]).endpoint(wire.source[1]) if wire.source else (
        joint if joint is not None and wire.branch_side()=='start' else tuple(wire.start or wire.end or (0,0)))
    b=doc.node(wire.target[0]).endpoint(wire.target[1]) if wire.target else (
        joint if joint is not None and wire.branch_side()=='end' else tuple(wire.end or (0,0)))
    return a,b


def port_clearance(doc,vertices,source,target):
    result=list(vertices)
    # A port must be approached horizontally from outside the frame. When a
    # segment or block moves, shift an edge-aligned vertical run one grid cell
    # outward; preserve junction IDs on the shifted run. No other nets are read
    # or attached here: crossings remain purely visual.
    for reverse,ep in ((False,source),(True,target)):
        if not ep:continue
        if reverse:result.reverse()
        p=result[0][1];node=doc.node(ep[0]);direction=1 if node.source(ep[1]) else -1
        if len(result)>1 and result[1][1][0]==p[0] and result[1][1][1]!=p[1]:
            x=p[0]+direction*GRID
            if len(result)==2:
                result.insert(1,(None,(x,result[1][1][1])))
            last=1
            while last+1<len(result)-1 and result[last+1][1][0]==p[0]:last+=1
            for i in range(1,last+1):
                key,q=result[i];result[i]=(key,(x,q[1]))
            result.insert(1,(None,(x,p[1])))
        if reverse:result.reverse()
    return result


def sketch_path(doc,first,bends,destination):
    node=doc.node(first[0]);a=node.endpoint(first[1])
    result=[a,(a[0]+(GRID if node.source(first[1]) else -GRID),a[1])]
    for point in [*bends,destination]:
        q=(snap(point[0]),snap(point[1]));previous=result[-1]
        if previous[0]!=q[0] and previous[1]!=q[1]:result.append((q[0],previous[1]))
        result.append(q)
    matches=[(n.id,p.name) for n in doc.nodes for p in n.ports()
             if (n.id,p.name)!=tuple(first) and n.endpoint(p.name)==tuple(destination)]
    second=matches[0] if len(matches)==1 else None
    result=[p for _,p in port_clearance(doc,[(None,p) for p in result],first,second)]
    clean=[]
    for point in result:
        if clean and clean[-1]==point:continue
        while len(clean)>1:
            a,b=clean[-2:]
            if not (a[0]==b[0]==point[0] or a[1]==b[1]==point[1]):break
            if (b[0]-a[0])*(point[0]-b[0])+(b[1]-a[1])*(point[1]-b[1])<0:break
            clean.pop()
        clean.append(point)
    return clean


def auto_route(doc, wire):
    """Orthogonal path, ordered source-to-target; supports one dangling end."""
    loose=junction_point(doc,wire) if wire.join_wire else tuple(wire.end or (0,0))
    a,b=wire_terminals(doc,wire)
    start=(a[0]+GRID,a[1]) if wire.source else a
    end=(b[0]-GRID,b[1]) if wire.target else b
    points=[a,start]
    if wire.join_wire:
        if wire.points:
            # With explicit bends, follow the same port-to-junction order as
            # the drawing preview. Do not insert an artificial perpendicular
            # stub: it can create a loop before the first requested bend.
            terminal=a if wire.source else b
            exitpoint=start if wire.source else end
            waypoints=wire.points if wire.source else reversed(wire.points)
            branch=[terminal,exitpoint]
            for point in [*waypoints,loose]:
                prev=branch[-1]
                if prev[0]!=point[0] and prev[1]!=point[1]:branch.append((point[0],prev[1]))
                branch.append(tuple(point))
            if wire.target:branch.reverse()
            return [p for i,p in enumerate(branch) if i==0 or p!=branch[i-1]]
        host=route(doc,doc.wire(wire.join_wire));j=loose;i=nearest_segment(host,*j)
        horizontal=host[i][1]==host[i+1][1]
        exitpoint=end if wire.target else start
        terminal=b if wire.target else a
        waypoints=list(wire.points if wire.target else reversed(wire.points))
        first=waypoints[0] if waypoints else exitpoint
        stub=(j[0],first[1] if first[1]!=j[1] else j[1]-40) if horizontal else (first[0] if first[0]!=j[0] else j[0]-40,j[1])
        branch=[j,stub]
        for point in [*waypoints,exitpoint,terminal]:
            prev=branch[-1]
            if prev[0]!=point[0] and prev[1]!=point[1]:branch.append((point[0],prev[1]))
            branch.append(tuple(point))
        if wire.source:branch.reverse()
        return [p for i,p in enumerate(branch) if i==0 or p!=branch[i-1]]
    if wire.points:
        for q in [*wire.points,end]:
            prev=points[-1]
            if prev[0]!=q[0] and prev[1]!=q[1]: points.append((q[0],prev[1]))
            points.append(tuple(q))
    elif start[0]<=end[0]:
        mid=snap((start[0]+end[0])/2); points.extend([(mid,start[1]),(mid,end[1]),end])
    else:
        y=snap(min(a[1],b[1])-60); points.extend([(start[0],y),(end[0],y),end])
    points.append(b)
    return [p for i,p in enumerate(points) if i==0 or p!=points[i-1]]


def nearest_segment(points,x,y):
    best=(float('inf'),0)
    for i,(a,b) in enumerate(zip(points,points[1:])):
        dx,dy=b[0]-a[0],b[1]-a[1]
        if not (dx or dy):continue
        t=max(0,min(1,((x-a[0])*dx+(y-a[1])*dy)/(dx*dx+dy*dy)))
        distance=(x-a[0]-t*dx)**2+(y-a[1]-t*dy)**2
        if distance<best[0]:best=(distance,i)
    return best[1]

def wire_path(doc,wire):
    if not wire.vertices:
        raw=auto_route(doc,wire)
        # Initial geometry consists of maximal straight segments.
        clean=[]
        for point in raw:
            if clean and point==clean[-1]:continue
            while len(clean)>1 and ((clean[-2][0]==clean[-1][0]==point[0]) or (clean[-2][1]==clean[-1][1]==point[1])):
                a,b=clean[-2],clean[-1]
                if (b[0]-a[0])*(point[0]-b[0])+(b[1]-a[1])*(point[1]-b[1])<0:break
                clean.pop()
            clean.append(point)
        return [(None,p) for p in clean]
    vertices=[(key,(x,y)) for key,x,y in wire.vertices]
    loose=junction_point(doc,wire) if wire.join_wire else tuple(wire.end or (0,0))
    start,end=wire_terminals(doc,wire)
    protected={w.join_vertex for w in doc.wires if w.join_wire==wire.id and w.join_vertex}
    # Move the adjacent elbow with its terminal, keeping the original
    # terminal-segment direction. Keep shared vertex IDs so every branch
    # follows the relocated junction instead of the old corner.
    if len(vertices)>2:
        original=list(vertices)
        for terminal,adjacent,point in ((0,1,start),(-1,-2,end)):
            key,corner=vertices[adjacent]
            old_terminal=original[terminal][1];old_corner=original[adjacent][1]
            if point==old_terminal or old_terminal==old_corner:continue
            if old_terminal[1]==old_corner[1]:vertices[adjacent]=(key,(corner[0],point[1]))
            elif old_terminal[0]==old_corner[0]:vertices[adjacent]=(key,(point[0],corner[1]))
    vertices[0]=(vertices[0][0],start);vertices[-1]=(vertices[-1][0],end)
    result=[vertices[0]]
    for key,p in vertices[1:]:
        prev=result[-1][1]
        if prev[0]!=p[0] and prev[1]!=p[1]:result.append((None,(p[0],prev[1])))
        result.append((key,p))
    # A junction dragged past the end of a straight host must not leave a
    # doubled-back tail. Keep it on the usable host span (inside port stubs).
    for i in range(1,len(result)-1):
        key,b=result[i];a=result[i-1][1];c=result[i+1][1]
        if key not in protected:continue
        axis=0 if a[1]==b[1]==c[1] else 1 if a[0]==b[0]==c[0] else None
        if axis is None or (b[axis]-a[axis])*(c[axis]-b[axis])>=0:continue
        low,high=sorted((a[axis],c[axis]))
        if axis==0:
            if i==1 and wire.source:low+=GRID
            if i==len(result)-2 and wire.target:high-=GRID
        if low<=high:
            point=list(b);point[axis]=max(low,min(high,b[axis]));result[i]=(key,tuple(point))
    result=port_clearance(doc,result,wire.source,wire.target)
    # Collapse redundant bends, retaining shared vertex IDs for connectivity.
    clean=[]
    for vertex in result:
        if clean and clean[-1][1]==vertex[1]:
            if clean[-1][0] not in protected:clean[-1]=vertex;continue
            if vertex[0] not in protected:continue
        while len(clean)>1 and clean[-1][0] not in protected:
            a,b,c=clean[-2][1],clean[-1][1],vertex[1]
            collinear=a[0]==b[0]==c[0] or a[1]==b[1]==c[1]
            if not collinear:break
            clean.pop()
        clean.append(vertex)
    if len(clean)==1:clean.append((None,clean[0][1]))
    return clean

def route(doc,wire):
    return [point for key,point in wire_path(doc,wire)]


def path_position(points,position):
    lengths=[abs(b[0]-a[0])+abs(b[1]-a[1]) for a,b in zip(points,points[1:])]
    distance=sum(lengths)*position
    for a,b,length in zip(points,points[1:],lengths):
        if length and distance<=length:
            t=distance/length; return a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t
        distance-=length
    return tuple(points[-1])


def project_to_path(points,x,y):
    """Return normalized distance along path and squared cursor distance."""
    total=sum(abs(b[0]-a[0])+abs(b[1]-a[1]) for a,b in zip(points,points[1:]))
    best=(float('inf'),0); travelled=0
    for a,b in zip(points,points[1:]):
        dx,dy=b[0]-a[0],b[1]-a[1]; length=abs(dx)+abs(dy)
        if not length: continue
        t=max(0,min(1,((x-a[0])*dx+(y-a[1])*dy)/(dx*dx+dy*dy)))
        px,py=a[0]+dx*t,a[1]+dy*t; dist=(x-px)**2+(y-py)**2
        candidate=(dist,(travelled+length*t)/total)
        if candidate[0]<best[0]: best=candidate
        travelled+=length
    return best[1],best[0]


def resize_node(node,original,corner,x,y):
    """Grid-snapped corner resize with a fixed opposite corner."""
    minw,minh=node.minimum_size(); left,top,right,bottom=original
    x,y=snap(x),snap(y)
    if 'w' in corner: left=min(x,right-minw)
    else: right=max(x,left+minw)
    if 'n' in corner: top=min(y,bottom-minh)
    else: bottom=max(y,top+minh)
    node.x,node.y,node.w,node.h=left,top,right-left,bottom-top
