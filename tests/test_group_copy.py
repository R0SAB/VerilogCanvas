import copy
import unittest
from model import TextComment, Node, Port, route, junction_point
from test_groups import grouped_design
from test_port_nets import design

class GroupCopyTests(unittest.TestCase):
    def test_comments_move_with_frozen_group_membership(self):
        d=grouped_design();d.comments.append(TextComment(id='note',text='Note',x=200,y=440,w=200,h=60))
        members=d.group_contents('g');comments={'g','note'}
        for dx,dy in [(100,60),(-200,-100),(20,40)]: d.move_group('g',dx,dy,members,comments)
        self.assertEqual((d.comment('note').x,d.comment('note').y),(120,440))
        self.assertEqual(d.comment_groups(),{'note':'g'})

    def test_copy_ports_instances_labels_and_branch(self):
        d,wi,wo=design()
        d.comments=[TextComment(id='g',kind='group',text='Group',x=0,y=0,w=1400,h=800),TextComment(id='note',text='Note',x=200,y=600,w=200,h=60)]
        d.nodes.append(Node(id='b',name='u_b',x=600,y=400,inputs=[Port('a','7:0')],outputs=[]))
        branch=d.connect(('b','a'),end=[420,160],join_wire=wi.id,join_position=.5)
        d.label_wire(wi.id,'data_in');d.label_wire(wo.id,'result')
        original=d.serialize();snapshot=d.group_snapshot('g');gid=d.paste_group(snapshot,1500,0)
        self.assertEqual(len(d.nodes),8);self.assertEqual(len(d.comments),4)
        self.assertEqual(len({n.name for n in d.nodes}),8)
        self.assertEqual({l.name for l in d.labels},{'data_in','data_in_1','result','result_1'})
        self.assertEqual(d.node('in').name,'data_in')
        clones=d.wires[3:];self.assertEqual(len(clones),3)
        self.assertEqual(junction_point(d,clones[-1]),(1920,160))
        self.assertNotEqual(clones[-1].join_vertex,branch.join_vertex)
        nets=d.nets();self.assertEqual(len(nets),4)
        for net in nets: self.assertFalse(set(net.wires)&{w.id for w in clones} and set(net.wires)&{wi.id,wo.id,branch.id})
        code=d.verilog();self.assertIn('data_in_1',code);self.assertIn('result_1',code)
        d.validate();self.assertEqual(snapshot, d.__class__.deserialize(original).group_snapshot('g'))
        gid2=d.paste_group(d.group_snapshot(gid),1500,0);self.assertNotEqual(gid,gid2)
        d.validate()

    def test_branch_terminal_segment_moves_shared_vertex(self):
        d,wi,_=design();d.nodes.append(Node(id='b',name='u_b',x=500,y=400,inputs=[Port('a','7:0')],outputs=[]))
        branch=d.connect(('b','a'),end=[420,160],join_wire=wi.id,join_position=.5)
        original=copy.deepcopy(branch.vertices);host=copy.deepcopy(wi.vertices)
        for offset in (20,60,-20,0):
            wi.vertices=copy.deepcopy(host)
            d.move_segment(branch,0,offset,0,original)
            self.assertEqual(junction_point(d,branch),(420+offset,160))
            self.assertEqual(route(d,branch)[0],(420+offset,160))
            self.assertTrue(all(a[0]==b[0] or a[1]==b[1] for a,b in zip(route(d,wi),route(d,wi)[1:])))
            d.validate()

if __name__=='__main__': unittest.main()
