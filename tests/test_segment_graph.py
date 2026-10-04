import copy
import unittest
from model import Document,Wire,route,junction_point,project_to_path,uid

class SegmentGraphTests(unittest.TestCase):
    def design(self):
        host=Wire(id='host',source=None,target=None,start=[0,120],end=[400,0],vertices=[[uid(),x,y] for x,y in [(0,120),(60,120),(60,0),(240,0),(400,0)]])
        branch=Wire(id='branch',source=None,target=None,end=[240,180],join_wire='host',join_side='start',vertices=[[uid(),240,0],[uid(),240,180]])
        d=Document(wires=[host,branch]);d.attach_vertex(branch,project_to_path(route(d,host),240,0)[0]);d.freeze_wire(host);d.freeze_wire(branch)
        return d,host,branch

    def check_case(self,side,offset,host_expected,branch_expected):
        d,host,branch=self.design();w=branch if side=='vertical' else host
        index=0 if side=='vertical' else next(i for i,(a,b) in enumerate(zip(w.vertices,w.vertices[1:])) if a[1:]==([60,0] if side=='left' else [240,0]))
        d.move_segment(w,index,offset if side=='vertical' else 0,0 if side=='vertical' else offset,copy.deepcopy(w.vertices))
        self.assertEqual(route(d,host),host_expected)
        self.assertEqual(route(d,branch),branch_expected)
        self.assertEqual(junction_point(d,branch),branch_expected[0]);d.validate()
        restored=Document.deserialize(d.serialize())
        self.assertEqual(route(restored,restored.wire('host')),host_expected)
        self.assertEqual(route(restored,restored.wire('branch')),branch_expected)
        self.assertEqual(len(d.nets()),1)

    def test_left_up(self):
        self.check_case('left',-60,[(0,120),(60,120),(60,-60),(240,-60),(240,0),(400,0)],[(240,0),(240,180)])
    def test_left_down(self):
        self.check_case('left',60,[(0,120),(60,120),(60,60),(240,60),(240,0),(400,0)],[(240,60),(240,180)])
    def test_right_up(self):
        self.check_case('right',-60,[(0,120),(60,120),(60,0),(240,0),(240,-60),(400,-60)],[(240,0),(240,180)])
    def test_right_down(self):
        self.check_case('right',60,[(0,120),(60,120),(60,0),(240,0),(240,60),(400,60)],[(240,60),(240,180)])
    def test_vertical_left(self):
        self.check_case('vertical',-180,[(0,120),(60,120),(60,0),(400,0)],[(60,120),(60,180)])
    def test_vertical_right(self):
        self.check_case('vertical',100,[(0,120),(60,120),(60,0),(340,0),(400,0)],[(340,0),(340,180)])

    def test_same_geometry_with_reversed_branch(self):
        for side,offset in [('left',-60),('left',60),('right',-60),('right',60),('vertical',-180),('vertical',100)]:
            expected=None
            for reverse in (False,True):
                d,host,branch=self.design()
                if reverse:
                    branch.join_side='end';branch.start=[240,180];branch.end=[240,0];branch.vertices.reverse()
                w=branch if side=='vertical' else host
                index=0 if side=='vertical' else next(i for i,(a,b) in enumerate(zip(w.vertices,w.vertices[1:])) if a[1:]==([60,0] if side=='left' else [240,0]))
                d.move_segment(w,index,offset if side=='vertical' else 0,0 if side=='vertical' else offset,copy.deepcopy(w.vertices))
                actual=(route(d,host),list(reversed(route(d,branch))) if reverse else route(d,branch))
                if expected is None:expected=actual
                else:self.assertEqual(actual,expected)
                d.validate()

    def test_descendant_on_shared_prefix_is_reparented(self):
        d,host,branch=self.design()
        child=Wire(id='child',source=None,target=None,join_wire=branch.id,join_side='start',end=[400,40],vertices=[[uid(),240,40],[uid(),400,40]])
        d.wires.append(child);d.attach_vertex(child,project_to_path(route(d,branch),240,40)[0])
        d.freeze_wire(host)
        index=next(i for i,v in enumerate(host.vertices) if v[1:]==[60,0])
        d.move_segment(host,index,0,80,copy.deepcopy(host.vertices))
        self.assertEqual(child.join_wire,host.id)
        self.assertEqual(junction_point(d,child),(240,40))
        self.assertEqual(junction_point(d,branch),(240,80));d.validate()
        self.assertEqual(len(d.nets()),1)

    def test_fully_shared_branch_is_valid_and_not_drawn_twice(self):
        d,host,branch=self.design();branch.end=[240,40];branch.vertices[-1][1:]=[240,40]
        index=next(i for i,v in enumerate(host.vertices) if v[1:]==[60,0])
        d.move_segment(host,index,0,80,copy.deepcopy(host.vertices))
        self.assertEqual(route(d,branch),[(240,40),(240,40)]);d.validate()
