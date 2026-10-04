import copy
import tempfile
import unittest
from pathlib import Path
from model import Document,Node,Port,DesignError,route,sketch_path,project_to_path,junction_point


def design():
    a=Node(id='a',name='driver',x=0,y=0,inputs=[],outputs=[Port('q','7:0')])
    b=Node(id='b',name='receiver',x=600,y=200,inputs=[Port('d','7:0')],outputs=[])
    d=Document(nodes=[a,b]);w=d.connect(('a','q'),('b','d'));return d,w

class ReplacementTests(unittest.TestCase):
    def test_labelled_stubs_keep_both_ends_when_only_port_is_deleted(self):
        from model import path_position
        for is_output in (False,True):
            for bends in ([],[[420,200],[420,300]]):
                with self.subTest(is_output=is_output,bends=bends):
                    node=Node(id='n',name='block',x=600,y=100,
                              inputs=[] if is_output else [Port('p','7:0')],
                              outputs=[Port('p','7:0')] if is_output else [])
                    d=Document(nodes=[node])
                    wire=d.connect(('n','p'),points=bends,end=[400,300])
                    label=d.label_wire(wire.id,'payload',.3)
                    before=route(d,wire);anchor=path_position(before,label.position)
                    d.remove_node('n')
                    self.assertEqual(route(d,wire),before)
                    self.assertEqual(dict(wire.loose_ends()),dict(start=list(before[0]),end=list(before[-1])))
                    self.assertEqual(path_position(route(d,wire),label.position),anchor)
                    restored=Document.deserialize(d.serialize())
                    self.assertEqual(route(restored,restored.wire(wire.id)),before)
                    d.nodes.append(node);self.assertEqual(d.attach_coincident(),1)
                    self.assertEqual(route(d,wire),before)

    def test_both_deleted_ports_keep_route_labels_and_width(self):
        d,w=design();d.label_wire(w.id,'payload');before=route(d,w)
        old=copy.deepcopy(d.nodes)
        d.remove_node('a');d.remove_node('b')
        self.assertEqual(route(d,w),before);self.assertEqual(len(w.loose_ends()),2)
        self.assertEqual(w.width_hint,8);self.assertEqual(d.labels[0].name,'payload')
        d.validate(electrical=False)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'partial.vsch';d.save(path);d=Document.load(path);w=d.wire(w.id)
        self.assertEqual(route(d,w),before)
        d.nodes=old;self.assertEqual(d.attach_coincident(),2);d.validate()
        self.assertEqual(route(d,w),before);self.assertIn('.d(payload)',d.verilog())

    def test_deleted_branch_port_keeps_junction_and_free_end(self):
        for branch_source in (False,True):
            d,w=design()
            if branch_source:
                d.remove_node('a')
                n=Node(id='c',name='new_driver',x=-200,y=400,inputs=[],outputs=[Port('p','7:0')])
            else:n=Node(id='c',name='consumer',x=800,y=400,inputs=[Port('p','7:0')],outputs=[])
            d.nodes.append(n)
            b=d.connect(('c','p'),end=[420,160],join_wire=w.id,join_position=.5)
            path=route(d,b);joint=junction_point(d,b);key=b.join_vertex
            d.remove_node('c')
            self.assertEqual(route(d,b),path);self.assertEqual(junction_point(d,b),joint)
            self.assertEqual(b.join_vertex,key);self.assertEqual(len(b.loose_ends()),1)
            restored=Document.deserialize(d.serialize());self.assertEqual(route(restored,restored.wire(b.id)),path)
            d.nodes.append(n);d.attach_coincident(node_ids={'c'});d.validate()
            self.assertEqual(route(d,b),path)

    def test_invalid_replacement_is_editable_and_roundtrips(self):
        d,w=design();old=copy.deepcopy(d.node('b'));d.remove_node('b')
        old.inputs=[Port('d','15:0',signed=True)];d.nodes.append(old)
        self.assertEqual(d.attach_coincident(),1)
        issues=d.connection_issues();message='\n'.join(i['message'] for i in issues)
        self.assertIn('Width mismatch',message);self.assertIn('Signedness mismatch',message)
        self.assertIn(('b','d'),{tuple(ep) for i in issues for ep in i['ports']})
        d.validate(electrical=False);restored=Document.deserialize(d.serialize())
        with self.assertRaises(DesignError):restored.verilog()
        restored.node('b').inputs=[Port('d','7:0')]
        self.assertEqual(restored.connection_issues(),[]);restored.verilog()

    def test_signedness_is_visible_but_legal_module_connection_exports(self):
        d,w=design();d.node('b').inputs[0].signed=True
        self.assertTrue(any('Signedness mismatch' in i['message'] for i in d.connection_issues()))
        self.assertIn('endmodule',d.verilog())

    def test_port_rename_detach_and_reattach(self):
        d,w=design();original=route(d,w)
        d.detach_port(('b','d'));d.node('b').inputs[0].name='replacement'
        d.attach_coincident(node_ids={'b'})
        self.assertEqual(w.target,('b','replacement'));self.assertEqual(route(d,w),original)

    def test_ambiguous_overlap_does_not_guess(self):
        d,w=design();replacement=copy.deepcopy(d.node('b'));d.remove_node('b')
        second=copy.deepcopy(replacement);second.id='c';second.name='other';d.nodes.extend([replacement,second])
        self.assertEqual(d.attach_coincident(),0);self.assertIsNone(w.target)

    def test_wrong_direction_can_be_saved_and_fixed(self):
        d,w=design();d.remove_node('b');n=Node(id='b',name='wrong',x=360,y=200,inputs=[],outputs=[Port('p','7:0')]);d.nodes.append(n)
        self.assertEqual(d.attach_coincident(),1)
        self.assertTrue(any('Multiple drivers' in i['message'] for i in d.connection_issues()))
        Document.deserialize(d.serialize())

    def test_preview_equals_commit_on_branch_without_manual_bends(self):
        d,w=design();n=Node(id='c',name='consumer',x=600,y=400,inputs=[Port('d','7:0')],outputs=[]);d.nodes.append(n)
        point=route(d,w)[1];first=('c','d');pos=project_to_path(route(d,w),*point)[0]
        drawn=sketch_path(d,first,[],point)
        b=d.connect(first,end=list(point),join_wire=w.id,join_position=pos,drawn_path=drawn)
        self.assertEqual(route(d,b),list(reversed(drawn)))

    def test_preview_equals_commit_between_ports_both_directions(self):
        for backwards in (False,True):
            d,w=design();d.remove_wire(w.id)
            first,second=(('b','d'),('a','q')) if backwards else (('a','q'),('b','d'))
            drawn=sketch_path(d,first,[[420,360]],d.node(second[0]).endpoint(second[1]))
            w=d.connect(first,second,points=[[420,360]],drawn_path=drawn)
            self.assertEqual(route(d,w),list(reversed(drawn)) if backwards else drawn)

if __name__=='__main__':unittest.main()
