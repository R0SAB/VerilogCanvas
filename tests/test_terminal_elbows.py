import unittest
from model import Document,Node,Port,route,junction_point

class TerminalElbowTests(unittest.TestCase):
    def design(self):
        a=Node(id='a',kind='input',name='adc_dry',x=0,y=0,inputs=[],outputs=[Port('adc_dry')]);a.normalize()
        b=Node(id='b',name='sink',x=600,y=200,inputs=[Port('a')],outputs=[])
        d=Document(nodes=[a,b]);w=d.connect(('a','adc_dry'),('b','a'))
        return d,w

    def test_source_and_destination_follow_port_height(self):
        d,w=self.design();a=d.node('a');b=d.node('b')
        for y in (100,180,300,0):
            a.y=y;points=route(d,w)
            self.assertEqual(points[0][1],points[1][1])
            self.assertEqual(min(p[1] for p in points),min(a.endpoint('adc_dry')[1],b.endpoint('a')[1]))
            self.assertEqual(max(p[1] for p in points),max(a.endpoint('adc_dry')[1],b.endpoint('a')[1]))
        for y in (300,100,0):
            b.y=y;points=route(d,w)
            self.assertEqual(points[-1][1],points[-2][1])
        self.assertEqual(route(Document.deserialize(d.serialize()),w),route(d,w))

    def test_shared_junction_is_not_removed(self):
        d,w=self.design();sink=Node(id='c',name='other',x=800,y=400,inputs=[Port('a')],outputs=[]);d.nodes.append(sink)
        branch=d.connect(('c','a'),end=[420,160],join_wire=w.id,join_position=.5)
        before=junction_point(d,branch);key=branch.join_vertex
        d.node('a').y=120
        self.assertEqual(junction_point(d,branch),(420,180))  # Clamp to the visible shortened segment.
        self.assertIn(key,{v[0] for v in w.vertices});d.validate()

    def test_materialized_reverse_stub_is_trimmed(self):
        d,w=self.design();d.node('a').y=100
        w.vertices=[['start',240,160],['new',420,160],['old',420,60],['lower',420,260],['end',600,260]]
        self.assertEqual(route(d,w),[(240,160),(420,160),(420,260),(600,260)])

    def test_junction_on_straight_wire_follows_either_port(self):
        for moved in ('a','b'):
            with self.subTest(moved=moved):
                d,w=self.design();d.node('b').y=0
                w.vertices=[['start',240,60],['end',600,60]]
                sink=Node(id='c',name='other',x=800,y=400,inputs=[Port('a')],outputs=[])
                d.nodes.append(sink)
                branch=d.connect(('c','a'),end=[420,60],join_wire=w.id,join_position=.5)
                key=branch.join_vertex
                for y in (160,240,-80,0):
                    d.node(moved).y=y
                    expected=(420,y+60)
                    self.assertEqual(junction_point(d,branch),expected)
                    self.assertEqual(route(d,branch)[0],expected)
                    self.assertIn(expected,route(d,w))
                    self.assertEqual(branch.join_vertex,key)
                    for wire in (w,branch):
                        points=route(d,wire)
                        self.assertTrue(all(a[0]==b[0] or a[1]==b[1] for a,b in zip(points,points[1:])))
                    restored=Document.deserialize(d.serialize())
                    self.assertEqual(junction_point(restored,restored.wire(branch.id)),expected)
                    d.validate()

if __name__=='__main__':unittest.main()
