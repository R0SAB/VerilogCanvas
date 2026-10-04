import unittest
from model import Document, Node, Port, Wire, route

class ManualBranchTests(unittest.TestCase):
    def test_manual_bends_follow_port_to_junction_preview(self):
        for source in (False, True):
            with self.subTest(source=source):
                node=Node(id='n',name='u_n',x=2000 if not source else 1600,y=-1560,
                          inputs=[] if source else [Port('p')],outputs=[Port('p')] if source else [])
                d=Document(nodes=[node])
                host=Wire('host',None,None,[],vertices=[['a',1680,-980],['j',1780,-980],['b',2180,-980]],end=[1680,-980] if source else [2180,-980])
                # Anchor the host to a real source, keeping this fixture minimal.
                driver=Node(id='driver',name='driver',x=2180 if source else 1400,y=-1040,inputs=[Port('p')] if source else [],outputs=[] if source else [Port('p')])
                d.nodes.append(driver)
                if source:host.target=('driver','p')
                else:host.source=('driver','p')
                d.wires.append(host)
                w=Wire('branch',('n','p') if source else None,None if source else ('n','p'),[[1900,-980]],end=[1780,-980],join_wire='host',join_vertex='j')
                d.wires.append(w)
                pts=route(d,w)
                if source:pts.reverse()
                self.assertEqual(pts,[(1780,-980),(1900,-980),(1900,-1500),node.endpoint('p')])
                d.freeze_wire(w)
                restored=Document.deserialize(d.serialize())
                self.assertEqual(route(restored,restored.wire('branch')),route(d,w))

if __name__=='__main__':unittest.main()
