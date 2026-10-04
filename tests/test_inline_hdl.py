import copy
import tempfile
import unittest
from pathlib import Path
from model import Document,Node,Port,TextComment,DesignError
from inline_hdl import parse_inline,update_interface
from schematic_text import encode_document,decode_document
from recover_hdl import recover
try:
    from pyslang import ast,syntax
except ImportError:
    ast=syntax=None


def inline_design(source,language='verilog',declarations=''):
    block=Node(kind='inline',name='processing',x=400,y=200,w=400)
    update_interface(block,source)
    d=Document(nodes=[block],language=language,declarations=declarations)
    for index,p in enumerate(block.ports()):
        output=block.source(p.name)
        port=copy.deepcopy(p)
        # Top-level ports use evaluated ranges, with no dependency on block parameters.
        port.span=':'.join(str(v) for v in p.packed_bounds(block.params)[0]) if p.span else ''
        port.packed_extra=[':'.join(map(str,r)) for r in p.packed_bounds(block.params)[1:]]
        port.unpacked=[':'.join(map(str,r)) for r in p.array_bounds(block.params)]
        top=Node(kind='output' if output else 'input',name=p.name,inputs=[port] if output else [],outputs=[] if output else [port],x=1000 if output else 0,y=200+index*160)
        top.normalize();d.nodes.append(top);d.connect((block.id,p.name),(top.id,p.name))
    return d,block

class InlineTests(unittest.TestCase):
    def test_interface_widths_and_comments(self):
        source='// input fake;\nlocalparam MSB=15;\ninput wire [MSB:0] a, b;\noutput reg [MSB:0] y;\nalways @* begin y=a+b; end\n'
        parsed=parse_inline(source)
        self.assertEqual([p.name for p in parsed.inputs],['a','b']);self.assertEqual(parsed.outputs[0].width({}),16)
        self.assertNotIn('output reg',parsed.body);self.assertIn('// input fake;',parsed.body)
        self.assertFalse(parsed.requires_sv)

    def test_reject_bad_interface(self):
        for source in ['input wire [7:0 a;','input a; output a;','inout a;','input magic a;','module wrong; endmodule','`include "file.v"','input a']:
            with self.subTest(source=source),self.assertRaises(DesignError):parse_inline(source)

    def test_source_is_authoritative(self):
        d,n=inline_design('input a; output y; assign y = a;')
        n.inputs.append(Port('ghost'))
        with self.assertRaisesRegex(DesignError,'does not match'):d.validate()

    def test_raw_roundtrip_backup_and_recovery(self):
        source='input wire a;\noutput wire y;\n// Русский текст, "quotes", backslash \\\nassign y = a;\n'
        d,n=inline_design(source,declarations='// Shared declarations\nlocalparam LIMIT = 7;\n')
        raw=encode_document(d)
        self.assertIn(source.encode(),raw);self.assertEqual(Document.deserialize(decode_document(raw)).serialize(),d.serialize())
        damaged=b'BROKEN HEADER\n'+raw[raw.index(b'// ===== BEGIN HDL'):]
        recovered=recover(damaged);self.assertEqual(len(recovered),2);self.assertEqual(recovered[1][1],source.encode());self.assertTrue(recovered[1][2])
        truncated=damaged[:damaged.rfind(b'\n// ===== END HDL')]
        self.assertFalse(recover(truncated)[1][2])
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'design.vsch';d.save(path);before=path.read_bytes()
            n.x+=20;d.save(path)
            self.assertEqual(path.with_suffix('.vsch.bak').read_bytes(),before)
            self.assertEqual(Document.load(path).serialize(),d.serialize())

    def test_damaged_record_fails_without_discarding_source(self):
        d,n=inline_design('input a; output y; assign y=a;')
        raw=encode_document(d)
        with self.assertRaises(DesignError):decode_document(raw[:-15])
        self.assertIn(n.hdl_source.encode(),raw)

    def test_systemverilog_export_guard(self):
        d,n=inline_design('input logic a; output logic y; always_comb y=~a;','systemverilog')
        with self.assertRaisesRegex(DesignError,'requires SystemVerilog'):d.verilog('verilog')
        self.assertIn('always_comb',d.verilog())

    def test_group_copy_keeps_source_but_shared_port_conflicts_require_renaming(self):
        d,n=inline_design('input wire a; output wire y; wire temporary; assign temporary=~a; assign y=temporary;')
        d.comments.append(TextComment(id='group',kind='group',text='Inline group',x=-100,y=100,w=1600,h=1200))
        gid=d.paste_group(d.group_snapshot('group'));clones=[v for v in d.nodes if v.kind=='inline']
        self.assertEqual(len(clones),2);self.assertEqual(clones[0].hdl_source,clones[1].hdl_source)
        self.assertNotEqual(clones[0].name,clones[1].name)
        self.assertEqual(len(d.group_contents(gid)[0]),3)
        with self.assertRaisesRegex(DesignError,'different existing net'):d.verilog()

    @unittest.skipIf(ast is None,'pyslang unavailable')
    def test_hdl_compilation_comb_sequential_shared_scope_arrays(self):
        cases=[
            ('input wire a; output reg y; always @* begin y=~a; end','verilog',''),
            ('input logic clk, reset, enable; output logic ready; logic [3:0] counter; always_ff @(posedge clk) begin if(reset) counter<=0; else if(enable) counter<=counter+1; end assign ready=(counter==LIMIT);','systemverilog','localparam LIMIT=7;'),
            ('input logic [1:0] modulation; output logic mode; assign mode=(modulation==MOD_AM);','systemverilog',"typedef enum logic [1:0] { MOD_AM=0, MOD_FM=1 } modulation_t;"),
            ('input wire a; output wire y; wire inline_processing_a; assign inline_processing_a=~a; assign y=inline_processing_a;','verilog',''),
            ('input logic [7:0] a [0:3]; output logic [7:0] y [0:3]; assign y=a;','systemverilog',''),
            ('parameter WIDTH=8; input wire [WIDTH-1:0] a; output reg [WIDTH-1:0] y; function [WIDTH-1:0] calc; input [WIDTH-1:0] v; begin calc=~v; end endfunction always @* y=calc(a);','verilog',''),
        ]
        for source,language,declarations in cases:
            with self.subTest(source=source):
                d,n=inline_design(source,language,declarations);code=d.verilog()
                comp=ast.Compilation();comp.addSyntaxTree(syntax.SyntaxTree.fromText(code))
                self.assertFalse([str(diag.code) for diag in comp.getAllDiagnostics() if diag.isError()],code)

if __name__=='__main__':unittest.main()
