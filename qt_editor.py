"""Complete Qt editor built on the retained, cached schematic scene."""
import copy
import math
import sys
import tempfile
from pathlib import Path
from PySide6.QtCore import Qt, QPointF, QRectF, QTimer, QSettings, QSize, QLineF
from PySide6.QtGui import QAction, QKeySequence, QPainter, QPainterPath, QColor, QIcon, QPixmap, QImage, QPainterPathStroker
from PySide6.QtWidgets import (QApplication, QToolBar, QLabel, QComboBox, QLineEdit,
    QFileDialog, QMessageBox, QInputDialog, QMenu, QGraphicsPathItem, QGraphicsItem)
from qt_app import (Window, DiagramView, NodeItem, CommentItem, WireItem, LabelItem,
    BG, PANEL, TEXT, GREEN, AMBER, BLUE, ERROR, pen)
from qt_dialogs import (EditorDialog, InlineDialog, CommentDialog, DeclarationsDialog,
    PortMappingDialog, PreviewDialog, choose_hdl)
from model import (Document, Node, Port, TextComment, DesignError, GRID, COORD_LIMIT,
    identifier, uid, snap, route, path_position, project_to_path, sketch_path, resize_node, nearest_segment)
from inline_hdl import DEFAULT_SOURCE, update_interface


def icon(name):
    """Small conventional line icons, independent of desktop icon themes."""
    pix=QPixmap(24,24);pix.fill(Qt.GlobalColor.transparent);p=QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing);p.setPen(pen(QApplication.palette().buttonText().color().lighter(125).name(),1.7));p.setBrush(Qt.BrushStyle.NoBrush)
    def lines(points):
        path=QPainterPath();path.moveTo(*points[0])
        for point in points[1:]:path.lineTo(*point)
        p.drawPath(path)
    if name=='new':
        lines([(5,2),(15,2),(20,7),(20,22),(5,22),(5,2)]);lines([(15,2),(15,7),(20,7)])
    elif name=='open':
        lines([(3,19),(3,5),(10,5),(12,8),(21,8)]);lines([(3,19),(7,10),(23,10),(19,19),(3,19)])
    elif name in ('save','save_as'):
        lines([(3,3),(18,3),(21,6),(21,21),(3,21),(3,3)]);p.drawRect(7,3,9,6);p.drawRect(7,14,10,7)
        if name=='save_as':p.setPen(pen(AMBER,3));lines([(14,20),(22,12)])
    elif name=='copy':p.drawRect(3,3,12,14);p.drawRect(8,8,12,14)
    elif name=='paste':p.drawRect(5,5,15,17);p.drawRect(9,2,7,5);lines([(9,12),(16,12)]);lines([(9,16),(16,16)])
    elif name=='delete':
        lines([(3,6),(21,6)]);lines([(8,6),(8,3),(16,3),(16,6)]);lines([(6,6),(7,22),(18,22),(19,6)])
        lines([(10,10),(10,18)]);lines([(15,10),(15,18)])
    elif name in ('undo','redo'):
        if name=='redo':p.translate(24,0);p.scale(-1,1)
        path=QPainterPath();path.moveTo(20,19);path.cubicTo(23,6,12,5,4,10);p.drawPath(path);lines([(4,4),(4,10),(10,11)])
    elif name=='fit':
        for x,y,sx,sy in [(3,3,1,1),(21,3,-1,1),(3,21,1,-1),(21,21,-1,-1)]:lines([(x,y+6*sy),(x,y),(x+6*sx,y)])
        p.drawRect(8,8,8,8)
    p.end();return QIcon(pix)


class Editable:
    def mouseDoubleClickEvent(self,event):
        self.owner.cancel_drag();self.owner.edit_key(self.kind,self.key);event.accept()


class EditableNode(Editable,NodeItem):
    def refresh_layout(self):
        self.prepareGeometryChange();n=self.n
        self.rect=QRectF(-312 if n.transforms else -7,-7,n.w+(319 if n.transforms else 14),n.h+14)
        self.sync_position();self.update()
    def shape(self):
        path=super().shape()
        if self.n.kind in ('module','inline'):
            corners=[(self.n.w,self.n.h)] if not self.isSelected() else [(0,0),(self.n.w,0),(0,self.n.h),(self.n.w,self.n.h)]
            for x,y in corners:path.addRect(QRectF(x-6,y-6,12,12))
        return path
    def hoverMoveEvent(self,event):
        super().hoverMoveEvent(event);p=event.pos();n=self.n
        if self.owner.port_at(event.scenePos()):
            self.setCursor(Qt.CursorShape.ArrowCursor);return
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        if n.kind in ('module','inline'):
            for x,y,cursor in [(n.w,n.h,Qt.CursorShape.SizeFDiagCursor),(0,0,Qt.CursorShape.SizeFDiagCursor),(n.w,0,Qt.CursorShape.SizeBDiagCursor),(0,n.h,Qt.CursorShape.SizeBDiagCursor)]:
                if (self.isSelected() or (x==n.w and y==n.h)) and math.hypot(p.x()-x,p.y()-y)<=9/self.owner.view.transform().m11():self.setCursor(cursor);break
    def paint(self,p,option,widget=None):
        super().paint(p,option,widget)
        if self.n.kind in ('module','inline') and not self.isSelected() and not self.owner.exporting:
            p.setPen(pen('#71849b',1));p.drawLine(self.n.w-9,self.n.h-3,self.n.w-3,self.n.h-9)
            p.drawLine(self.n.w-5,self.n.h-3,self.n.w-3,self.n.h-5)


class EditableComment(Editable,CommentItem):
    def refresh_layout(self):
        from PySide6.QtGui import QFontMetricsF
        from qt_app import font
        self.prepareGeometryChange();c=self.c;margin=12 if self.group else 0
        self.caption=QFontMetricsF(font(c.font_size)).boundingRect(QRectF(0,0,c.w-2*margin,100000),Qt.TextFlag.TextWordWrap,c.text)
        self.height=c.h if self.group else max(c.h,self.caption.height())
        self.rect=QRectF(-7,-7,c.w+14,max(self.height,self.caption.height()+16)+14)
        self.setPos(c.x,c.y);self.update()
    def shape(self):
        path=super().shape()
        if self.isSelected() or self.group:path.addRect(QRectF(self.c.w-6,self.height-6,12,12))
        return path
    def hoverMoveEvent(self,event):
        p=event.pos();near=(self.isSelected() or self.group) and math.hypot(p.x()-self.c.w,p.y()-self.height)<=9/self.owner.view.transform().m11()
        self.setCursor(Qt.CursorShape.SizeFDiagCursor if near else Qt.CursorShape.SizeAllCursor)
    def paint(self,p,option,widget=None):
        super().paint(p,option,widget)
        if self.isSelected() and not self.owner.exporting:
            p.setPen(pen(BG));p.setBrush(QColor(GREEN));p.drawRect(QRectF(self.c.w-4,self.height-4,8,8))
        elif self.group and not self.owner.exporting:
            p.setPen(pen('#aebdce',1.5));p.drawLine(self.c.w-10,self.height-3,self.c.w-3,self.height-10)
            p.drawLine(self.c.w-6,self.height-3,self.c.w-3,self.height-6)


class SegmentItem(QGraphicsItem):
    """A separately hit-tested and painted straight wire edge."""
    def __init__(self,wire,index):
        super().__init__(wire);self.wire=wire;self.index=index
        self.kind='wire';self.key=wire.key;self.rect=QRectF();self.line=None
        self.setAcceptHoverEvents(True);self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
    def boundingRect(self):return self.rect
    def shape(self):
        path=QPainterPath()
        if self.line is not None:
            path.moveTo(self.line.p1());path.lineTo(self.line.p2())
            stroke=QPainterPathStroker();stroke.setWidth(12);return stroke.createStroke(path)
        return path
    def refresh(self):
        self.prepareGeometryChange();points=self.wire.points
        self.line=QLineF(QPointF(*points[self.index]),QPointF(*points[self.index+1])) if self.index+1<len(points) else None
        self.rect=self.shape().boundingRect();self.update()
    def paint(self,p,option,widget=None):
        if self.line is None:return
        w=self.wire;bus=w.owner.widths.get(w.key,w.w.width_hint)>1
        selected=w.isSelected() and (w.active_segment is None or w.active_segment==self.index)
        p.setPen(pen(GREEN if selected else BLUE if bus else '#a8c4df',4 if bus else 1.5));p.drawLine(self.line)
    def mousePressEvent(self,event):
        self.wire.active_segment=self.index
        self.wire.owner.begin_segment_drag(self.wire,self.index,event.scenePos(),event.modifiers());event.accept()
    def mouseMoveEvent(self,event):self.wire.owner.move_drag(event.scenePos());event.accept()
    def mouseReleaseEvent(self,event):self.wire.owner.finish_drag();event.accept()
    def mouseDoubleClickEvent(self,event):self.wire.mouseDoubleClickEvent(event)
    def hoverMoveEvent(self,event):
        self.wire.hoverMoveEvent(event);self.setCursor(self.wire.cursor());self.setToolTip(self.wire.toolTip())


class EditableWire(Editable,WireItem):
    def __init__(self,owner,wire):
        self.segments=[];self.active_segment=None;super().__init__(owner,wire)
    def refresh(self):
        super().refresh()
        while len(self.segments)<len(self.points)-1:self.segments.append(SegmentItem(self,len(self.segments)))
        for item in self.segments:item.refresh()
    def hoverMoveEvent(self,event):
        i=nearest_segment(self.points,event.scenePos().x(),event.scenePos().y())
        self.setCursor(Qt.CursorShape.SizeVerCursor if self.points[i][1]==self.points[i+1][1] else Qt.CursorShape.SizeHorCursor)
        self.setToolTip('\n'.join(self.owner.bad_wires.get(self.key,[])) or 'Drag this segment; Alt+drag moves a completely detached wire component. Double-click to name the net.')
    def itemChange(self,change,value):
        if change==QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            for item in self.segments:item.update()
        return super().itemChange(change,value)
    def paint(self,p,option,widget=None):
        bus=self.owner.widths.get(self.key,self.w.width_hint)>1;color=BLUE if bus else '#a8c4df'
        if self.joint and getattr(self,'draw_joint',True):
            p.setPen(pen(BG));p.setBrush(QColor(color));p.drawEllipse(QPointF(*self.joint),5,5)
        for _,point in self.loose:
            p.setPen(pen(ERROR if self.key in self.owner.bad_wires else color,2));p.setBrush(QColor(BG));p.drawEllipse(QPointF(*point),5,5)

class EditableLabel(Editable,LabelItem):pass


class EditorView(DiagramView):
    def mousePressEvent(self,event):
        o=self.owner;point=self.mapToScene(event.position().toPoint());o.last_point=point
        if event.button()==Qt.MouseButton.RightButton:
            if o.pending or o.label_mode:o.cancel_drawing()
            else:o.context_menu(point,event.globalPosition().toPoint())
            event.accept();return
        if event.button()==Qt.MouseButton.LeftButton:
            ep=o.port_at(point)
            if o.label_mode:
                near=o.nearest_wire(point)
                if near:o.cancel_drawing();o.place_label(near[0],near[1])
                event.accept();return
            if o.pending:
                if ep:
                    if ep!=o.pending:o.commit_wire(second=ep)
                    else:o.cancel_drawing()
                else:
                    near=o.nearest_wire(point,exclude=o.pending_wire)
                    if near:o.commit_wire(join_wire=near[0],join_position=near[1])
                    else:
                        bend=[snap(point.x()),snap(point.y())]
                        if not o.bends or bend!=o.bends[-1]:o.bends.append(bend)
                        o.preview_wire(point)
                event.accept();return
            if ep:
                o.start_wire(ep);event.accept();return
        super().mousePressEvent(event)

    def mouseMoveEvent(self,event):
        self.owner.last_point=self.mapToScene(event.position().toPoint())
        if self.owner.pending:self.owner.preview_wire(self.owner.last_point)
        super().mouseMoveEvent(event)

    def mouseDoubleClickEvent(self,event):
        if self.owner.pending:
            self.owner.commit_wire(end=self.mapToScene(event.position().toPoint()));event.accept();return
        super().mouseDoubleClickEvent(event)

    def keyPressEvent(self,event):
        if event.key()==Qt.Key.Key_Escape:
            self.owner.cancel_drawing();self.owner.cancel_drag();event.accept();return
        if event.key() in (Qt.Key.Key_Return,Qt.Key.Key_Enter) and self.owner.pending:
            self.owner.commit_wire(end=self.owner.last_point);event.accept();return
        super().keyPressEvent(event)


class EditorWindow(Window):
    view_class=EditorView;node_class=EditableNode;comment_class=EditableComment
    wire_class=EditableWire;label_class=EditableLabel

    def __init__(self):
        self.pending=None;self.pending_wire=None;self.bends=[];self.preview_item=None
        self.label_mode=False;self.last_point=QPointF();self.clipboard=None;self.solo_selection=False;self.exporting=False
        self.settings=QSettings('VerilogCanvas','QtEditor')
        super().__init__()
        self.setStyleSheet('QToolTip { border: 2px solid black; background: #fffbdc; color: #151515; padding: 5px; } QToolBar { spacing: 4px; }')
        self.grid_choice.setCurrentText(self.settings.value('grid','Dots'))
        self.grid_choice.currentTextChanged.connect(lambda value:self.settings.setValue('grid',value))
        self.statusBar().showMessage('Click a port to draw a wire; click to add bends; Enter or double-click to finish a free end. Middle drag: pan. Ctrl+wheel: zoom.')

    def build_toolbar(self):
        self.actions={}
        file_menu=self.menuBar().addMenu('&File');edit_menu=self.menuBar().addMenu('&Edit');add_menu=self.menuBar().addMenu('&Add');view_menu=self.menuBar().addMenu('&View');help_menu=self.menuBar().addMenu('&Help')
        bar=QToolBar('File and editing');bar.setMovable(False);bar.setIconSize(QSize(22,22));self.addToolBar(bar)
        def action(key,label,fn,shortcut=None,menu=None,toolbar=None,picture=None):
            a=QAction(icon(picture) if picture else QIcon(),label,self);a.triggered.connect(lambda checked=False:fn())
            if shortcut:a.setShortcut(QKeySequence(shortcut));a.setToolTip(f'{label} ({shortcut})')
            if menu:menu.addAction(a)
            if toolbar:toolbar.addAction(a)
            self.actions[key]=a;return a
        action('new','New Schematic',self.new_document,'Ctrl+N',file_menu,bar,'new')
        action('open','Open…',self.open_dialog,'Ctrl+O',file_menu,bar,'open')
        action('save','Save',self.save,'Ctrl+S',file_menu,bar,'save')
        action('save_as','Save As…',lambda:self.save(True),'Ctrl+Shift+S',file_menu,bar,'save_as');bar.addSeparator()
        self.undo_action=action('undo','Undo',self.undo,'Ctrl+Z',edit_menu,bar,'undo')
        self.redo_action=action('redo','Redo',self.redo,'Ctrl+Y',edit_menu,bar,'redo');bar.addSeparator()
        action('copy','Copy',self.copy_selection,'Ctrl+C',edit_menu,bar,'copy')
        action('paste','Paste',self.paste,'Ctrl+V',edit_menu,bar,'paste')
        action('delete','Delete',self.delete,'Delete',edit_menu,bar,'delete')
        action('properties','Properties…',self.edit_selected,'Alt+Return',edit_menu,bar)
        action('route','Reset Wire Route',self.reset_route,None,edit_menu)
        bar.addSeparator()
        action('zoom_out','−',lambda:self.view.set_zoom(self.view.transform().m11()/1.2),None,view_menu,bar)
        action('zoom_in','+',lambda:self.view.set_zoom(self.view.transform().m11()*1.2),None,view_menu,bar)
        action('actual','100%',lambda:self.view.set_zoom(1),None,view_menu,bar)
        action('fit','Fit Diagram',self.fit,'Home',view_menu,bar,'fit')
        bar.addWidget(QLabel(' Grid: '));self.grid_choice=QComboBox();self.grid_choice.addItems(['Dots','Lines','Off']);self.grid_choice.currentTextChanged.connect(self.view.set_grid_mode);bar.addWidget(self.grid_choice)
        self.addToolBarBreak();objects=QToolBar('Objects');objects.setMovable(False);self.addToolBar(objects)
        for key,label,fn in [('module','Module',lambda:self.add_node('module')),('import','Import .v/.sv…',self.import_module),('inline','Inline HDL',lambda:self.add_node('inline')),('input','Input',lambda:self.add_node('input')),('output','Output',lambda:self.add_node('output')),('comment','Comment',lambda:self.add_comment('text')),('group','Group',lambda:self.add_comment('group')),('label','Net Label',self.start_label)]:
            action(key,'+ '+label,fn,None,add_menu,objects)
        objects.addSeparator();action('declarations','Declarations…',self.edit_declarations,None,edit_menu,objects)
        self.addToolBarBreak();output=QToolBar('HDL output');output.setMovable(False);self.addToolBar(output)
        self.language=QComboBox();self.language.addItems(['Verilog','SystemVerilog']);self.language.currentIndexChanged.connect(self.change_language);output.addWidget(self.language)
        self.output_path=QLineEdit();self.output_path.setReadOnly(True);self.output_path.setMinimumWidth(180);self.output_path.setPlaceholderText('Choose an output file with Export or Export As…')
        action('export','Export',self.export,'Ctrl+E',file_menu,output)
        action('export_as','Export As…',lambda:self.export(True),'Ctrl+Shift+E',file_menu,output)
        action('preview','Preview HDL',self.preview_hdl,'Ctrl+P',view_menu,output)
        action('png','Export PNG…',self.export_png,None,file_menu,output)
        output.addWidget(QLabel(' Output: '));output.addWidget(self.output_path)
        action('about','Help / About',self.about,'F1',help_menu)

    def rebuild(self):
        super().rebuild();self.refresh_wire_markers()

    def refresh_geometry(self,members=(),comments=(),wires=()):
        super().refresh_geometry(members,comments,wires);self.refresh_wire_markers()

    def refresh_wire_markers(self):
        """One marker per physical junction; two incident rays are just a bend.

        Join only explicit attachments, never unrelated geometric crossings or
        equal net labels. Work from cached geometry without electrical checks.
        """
        previous={wid:(getattr(item,'draw_joint',False),item.loose) for wid,item in self.wire_items.items()}
        parents={};candidates=[];free=[]
        def find(key):
            parents.setdefault(key,key)
            if parents[key]!=key:parents[key]=find(parents[key])
            return parents[key]
        def union(a,b):parents[find(a)]=find(b)
        for wid,item in self.wire_items.items():
            item.draw_joint=False;item.loose=[]
            for side,point in item.w.loose_ends():
                key=(wid,tuple(point));find(key);free.append((key,side,point))
            if item.joint is not None:
                key=(wid,tuple(item.joint));host=(item.w.join_wire,tuple(item.joint))
                union(key,host);candidates.append((key,item))
        groups={}
        for key in parents:groups.setdefault(find(key),[]).append(key)
        for key,side,point in free:
            if len(groups[find(key)])==1:self.wire_items[key[0]].loose.append((side,point))
        drawn=set()
        for key,item in candidates:
            root=find(key)
            if root in drawn:continue
            rays=set()
            for wid,(x,y) in groups[root]:
                for a,b in zip(self.wire_items[wid].points,self.wire_items[wid].points[1:]):
                    if a[1]==b[1]==y and min(a[0],b[0])<=x<=max(a[0],b[0]):
                        if min(a[0],b[0])<x:rays.add('left')
                        if max(a[0],b[0])>x:rays.add('right')
                    if a[0]==b[0]==x and min(a[1],b[1])<=y<=max(a[1],b[1]):
                        if min(a[1],b[1])<y:rays.add('up')
                        if max(a[1],b[1])>y:rays.add('down')
            if len(rays)>=3:item.draw_joint=True;drawn.add(root)
        for wid,item in self.wire_items.items():
            if previous[wid]!=(item.draw_joint,item.loose):item.update()

    def update_metrics(self):
        self.metrics.setText(f'{self.view.transform().m11()*100:.0f}%')

    def update_title(self):
        self.setWindowTitle(f'{"* " if self.doc.serialize()!=self.saved else ""}{self.path.name if self.path else "Untitled"} — VerilogCanvas Qt 1.2.2')
        self.undo_action.setEnabled(bool(self.history));self.redo_action.setEnabled(bool(self.future))
        self.language.blockSignals(True);self.language.setCurrentIndex(self.doc.language=='systemverilog');self.language.blockSignals(False)
        self.output_path.setText(self.doc.export_path);self.output_path.setToolTip(self.doc.export_path)

    def error(self,title,exc):QMessageBox.warning(self,title,str(exc))

    def apply(self,operation,selection=None):
        self.cancel_drawing();self.cancel_drag();before=self.doc.serialize();trial=copy.deepcopy(self.doc)
        try:result=operation(trial);trial.validate(electrical=False)
        except (ValueError,OSError,TypeError) as exc:self.error('Could Not Apply Change',exc);return None
        if trial.serialize()!=before:
            self.history.append(before);self.history=self.history[-100:];self.future=[];self.doc=trial;self.rebuild();self.update_title()
        if selection:self.select(*selection)
        return result

    def select(self,kind,key):
        self.scene.clearSelection();items={'node':self.node_items,'comment':self.comment_items,'wire':self.wire_items,'label':self.label_items}
        item=items[kind].get(key)
        if item:item.setSelected(True)

    def unique(self,base):
        used={n.name for n in self.doc.nodes}|{l.name for l in self.doc.labels}|{self.doc.top};name=base;i=1
        while name in used:name=f'{base}_{i}';i+=1
        return name

    def insertion_point(self):
        p=self.view.mapToScene(self.view.viewport().rect().center());return snap(p.x()-120),snap(p.y()-80)

    def add_node(self,kind,node=None,is_sv=False):
        self.cancel_drawing();x,y=self.insertion_point()
        n=node or Node(kind=kind,name=self.unique({'module':'u_module','inline':'inline_logic','input':'input_port','output':'output_port'}[kind]))
        n.x,n.y=x,y;n.name=self.unique(n.name)
        if kind in ('input','output'):
            n.inputs=[Port(n.name)] if kind=='output' else [];n.outputs=[Port(n.name)] if kind=='input' else [];n.normalize()
        if kind=='inline' and node is None:n.w=320;update_interface(n,DEFAULT_SOURCE)
        dlg=InlineDialog(self,n) if kind=='inline' else EditorDialog(self,n)
        if not dlg.exec():return
        n=dlg.value
        def operation(doc):
            doc.nodes.append(n);doc.attach_coincident(node_ids={n.id})
            if is_sv or dlg.imported_sv or any(p.requires_sv() for p in n.ports()):doc.language='systemverilog'
        self.apply(operation,('node',n.id))

    def import_module(self):
        self.cancel_drawing();result=choose_hdl(self)
        if result:self.add_node('module',*result)

    def add_comment(self,kind):
        self.cancel_drawing();x,y=self.insertion_point()
        dlg=CommentDialog(self,TextComment(text='',kind=kind,x=x,y=y,w=600 if kind=='group' else 360,h=400 if kind=='group' else 100))
        if dlg.exec():self.apply(lambda doc:doc.comments.append(dlg.value),('comment',dlg.value.id))

    def edit_selected(self):
        items=self.scene.selectedItems()
        if len(items)==1:self.edit_key(items[0].kind,items[0].key)
        else:self.statusBar().showMessage('Select one object to edit its properties.',4000)

    def edit_key(self,kind,key):
        self.cancel_drawing();self.cancel_drag()
        if kind=='wire':self.place_label(key);return
        if kind=='label':
            label=next(l for l in self.doc.labels if l.id==key);self.place_label(label.wire_id,label.position);return
        if kind=='comment':
            dlg=CommentDialog(self,self.doc.comment(key))
            if dlg.exec():self.apply(lambda doc:doc.comments.__setitem__(next(i for i,c in enumerate(doc.comments) if c.id==key),dlg.value),('comment',key))
            return
        old=self.doc.node(key);dlg=InlineDialog(self,old) if old.kind=='inline' else EditorDialog(self,old)
        if not dlg.exec():return
        n=dlg.value;mapping={}
        if old.kind=='inline':
            connected={ep[1] for w in self.doc.wires for ep in w.endpoints() if ep[0]==old.id};valid={p.name for p in n.ports()}
            removed=[p.name for p in old.ports() if p.name in connected and (p.name not in valid or old.source(p.name)!=n.source(p.name))]
            if removed:
                reconnect=PortMappingDialog(self,old,n,removed)
                if not reconnect.exec():return
                mapping=reconnect.value
        def operation(doc):
            valid={p.name for p in n.ports()}
            if old.kind not in ('input','output'):
                for p in old.ports():
                    if (p.name in mapping and mapping[p.name] is None) or (p.name not in valid and p.name not in mapping):doc.detach_port((old.id,p.name))
            doc.nodes[doc.nodes.index(doc.node(key))]=n
            for w in doc.wires:
                for attr in ('source','target'):
                    ep=getattr(w,attr)
                    if ep and ep[0]==key:
                        if old.kind in ('input','output'):setattr(w,attr,(key,n.name))
                        elif mapping.get(ep[1]) is not None:setattr(w,attr,(key,mapping[ep[1]]))
            if dlg.imported_sv or any(p.requires_sv() for p in n.ports()):doc.language='systemverilog'
            doc.attach_coincident(node_ids={key})
        self.apply(operation,('node',key))

    def edit_declarations(self):
        self.cancel_drawing();dlg=DeclarationsDialog(self,self.doc.declarations)
        if dlg.exec():self.apply(lambda doc:setattr(doc,'declarations',dlg.value))

    def change_language(self,index):self.apply(lambda doc:setattr(doc,'language','systemverilog' if index else 'verilog'))

    def active_group(self):
        items=self.scene.selectedItems()
        if self.solo_selection or len(items)!=1:return None
        item=items[0]
        if item.kind=='node':return self.groups.get(item.key)
        if item.kind=='comment':return item.key if item.c.kind=='group' else self.comment_groups.get(item.key)

    def copy_selection(self):
        gid=self.active_group();items=self.scene.selectedItems()
        if gid:self.clipboard=self.doc.group_snapshot(gid)
        elif len(items)==1 and items[0].kind in ('node','comment'):
            item=items[0];self.clipboard=copy.deepcopy(item.n if item.kind=='node' else item.c)
        else:self.statusBar().showMessage('Select one group, block or comment to copy.',4000);return
        self.statusBar().showMessage('Copied. Ctrl+V pastes a copy; instance and top-level port names are made unique.',4000)

    def paste(self):
        if self.clipboard is None:return
        if isinstance(self.clipboard,dict):
            gid=self.apply(lambda doc:doc.paste_group(self.clipboard))
            if gid:self.clipboard=self.doc.group_snapshot(gid);self.select('comment',gid);self.view.centerOn(self.comment_items[gid])
        else:
            obj=copy.deepcopy(self.clipboard);obj.id=uid();obj.x+=40;obj.y+=40
            if isinstance(obj,Node):
                obj.name=self.unique(obj.name)
                if obj.kind in ('input','output'):obj.ports()[0].name=obj.name
                def operation(doc):doc.nodes.append(obj);doc.attach_coincident(node_ids={obj.id})
                self.apply(operation,('node',obj.id))
            else:self.apply(lambda doc:doc.comments.append(obj),('comment',obj.id))
            self.clipboard=copy.deepcopy(obj)
        self.solo_selection=False

    def delete(self):
        selected=[(i.kind,i.key) for i in self.scene.selectedItems()]
        if not selected:return
        segment=None
        if len(selected)==1 and selected[0][0]=='wire':segment=self.wire_items[selected[0][1]].active_segment
        def operation(doc):
            for kind,key in selected:
                if kind=='node':doc.remove_node(key)
                elif kind=='wire':
                    if segment is None or not doc.remove_free_segment(key,segment):doc.remove_wire(key)
                elif kind=='comment':doc.comments=[c for c in doc.comments if c.id!=key]
                elif kind=='label':doc.labels=[l for l in doc.labels if l.id!=key]
        self.apply(operation)

    def reset_route(self):
        ids=[i.key for i in self.scene.selectedItems() if i.kind=='wire']
        self.apply(lambda doc:[doc.reset_wire_route(doc.wire(key)) for key in ids])

    def context_menu(self,point,global_point):
        item=next((i for i in self.scene.items(point) if hasattr(i,'kind')),None)
        if item and not item.isSelected():self.select(item.kind,item.key)
        menu=QMenu(self)
        for key in (('properties','copy','paste','delete','route') if item else ('module','import','inline','input','output','comment','group','label','paste')):menu.addAction(self.actions[key])
        menu.exec(global_point)

    def port_at(self,point):
        tolerance=max(5,8/self.view.transform().m11())
        for n in reversed(self.doc.nodes):
            for p in n.ports():
                x,y=n.endpoint(p.name)
                if math.hypot(x-point.x(),y-point.y())<=tolerance:return (n.id,p.name)

    def nearest_wire(self,point,exclude=None):
        best=None;limit=(12/self.view.transform().m11())**2
        for key,item in self.wire_items.items():
            if key==exclude:continue
            pos,distance=project_to_path(item.points,point.x(),point.y())
            if distance<=limit and (best is None or distance<best[2]):best=(key,pos,distance)
        return best

    def start_label(self):
        self.cancel_drawing();self.label_mode=True;self.view.setCursor(Qt.CursorShape.CrossCursor)
        self.statusBar().showMessage('Click a wire to add a net label. Matching names connect nets. Esc cancels.')

    def place_label(self,wire_id,position=.6):
        old=next((l for l in self.doc.labels if l.wire_id==wire_id),None)
        name,ok=QInputDialog.getText(self,'Net Label','Verilog/SV net name (matching names connect nets):',text=old.name if old else '')
        if ok:
            label=self.apply(lambda doc:doc.label_wire(wire_id,name.strip(),position,allow_invalid=True))
            if label:self.select('label',label.id)

    def cancel_drawing(self):
        if self.preview_item is not None:
            self.scene.removeItem(self.preview_item);self.preview_item=None
        self.pending=None;self.pending_wire=None;self.bends=[];self.label_mode=False
        self.view.unsetCursor()

    def start_wire(self,ep,wire_id=None,bends=None):
        self.cancel_drawing();self.pending=ep;self.pending_wire=wire_id;self.bends=bends or []
        self.preview_item=QGraphicsPathItem();self.preview_item.setPen(pen(AMBER,2,True));self.preview_item.setZValue(40)
        self.preview_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton);self.scene.addItem(self.preview_item)
        self.view.setCursor(Qt.CursorShape.CrossCursor)
        self.statusBar().showMessage('Click bends, another port or an existing wire. Enter / double-click ends in free space. Esc cancels.')

    def wire_destination(self,point):
        ep=self.port_at(point)
        if ep:return self.doc.node(ep[0]).endpoint(ep[1])
        near=self.nearest_wire(point,exclude=self.pending_wire)
        if near:return path_position(self.wire_items[near[0]].points,near[1])
        return (snap(point.x()),snap(point.y()))

    def preview_wire(self,point):
        if not self.pending:return
        points=sketch_path(self.doc,self.pending,self.bends,self.wire_destination(point));path=QPainterPath()
        if points:
            path.moveTo(*points[0])
            for p in points[1:]:path.lineTo(*p)
        self.preview_item.setPath(path)

    def commit_wire(self,second=None,end=None,join_wire=None,join_position=.5):
        if not self.pending:return
        first=self.pending;replace=self.pending_wire;points=copy.deepcopy(self.bends)
        if end is not None:
            end=[snap(end.x()),snap(end.y())] if isinstance(end,QPointF) else [snap(end[0]),snap(end[1])]
            while points and points[-1]==end:points.pop()
        destination=self.doc.node(second[0]).endpoint(second[1]) if second else path_position(self.wire_items[join_wire].points,join_position) if join_wire else end
        drawn=sketch_path(self.doc,first,points,destination)
        wire=self.apply(lambda doc:doc.connect(first,second,points,end,replace,join_wire,join_position,allow_invalid=True,drawn_path=drawn))
        if wire:self.select('wire',wire.id)

    def begin_drag(self,item,point,modifiers):
        self.solo_selection=bool(modifiers&Qt.KeyboardModifier.ControlModifier)
        corner=None;radius=9/self.view.transform().m11()
        if item.kind=='node' and item.n.kind in ('module','inline'):
            n=item.n
            for key,x,y in [('nw',n.x,n.y),('ne',n.x+n.w,n.y),('sw',n.x,n.y+n.h),('se',n.x+n.w,n.y+n.h)]:
                if (item.isSelected() or key=='se') and math.hypot(x-point.x(),y-point.y())<=radius:corner=key;break
        elif item.kind=='comment' and (item.isSelected() or item.group):
            c=item.c
            if math.hypot(c.x+c.w-point.x(),c.y+item.height-point.y())<=radius:corner='se'
        if corner:
            self.scene.clearSelection();item.setSelected(True);obj=item.n if item.kind=='node' else item.c
            self.drag=dict(kind='resize',before=self.doc.serialize(),item=item,corner=corner,original=(obj.x,obj.y,obj.x+obj.w,obj.y+obj.h));return
        if item.isSelected() and len(self.scene.selectedItems())>1 and not self.solo_selection and item.kind in ('wire','label'):
            selected=self.scene.selectedItems();members={i.key for i in selected if i.kind=='node'};comments={i.key for i in selected if i.kind=='comment'}
            groups={self.groups[key] for key in members if key in self.groups}
            groups.update(key for key in comments if self.comments[key].kind=='group')
            groups.update(self.comment_groups[key] for key in comments if key in self.comment_groups)
            for gid in groups:
                members.update(key for key,value in self.groups.items() if value==gid);comments.add(gid)
                comments.update(key for key,value in self.comment_groups.items() if value==gid)
            wires={i.key for i in selected if i.kind=='wire'}|self.doc.internal_wires(members)
            self.drag=dict(kind='objects',before=self.doc.serialize(),point=QPointF(point),offset=(0,0),item=item,members=members,comments=comments,wires=wires)
            self.capture_selected_labels();return
        super().begin_drag(item,point,modifiers)
        self.capture_selected_labels()
        if item.kind=='wire' and item.joint and getattr(item,'draw_joint',True) and math.hypot(point.x()-item.joint[0],point.y()-item.joint[1])<=radius:
            self.drag['kind']='junction'
        if self.drag and self.drag['kind']=='segment':self.capture_wire_component(item)

    def capture_wire_component(self,item):
        root=item.w
        while root.join_wire:root=self.doc.wire(root.join_wire)
        ids=self.affected_wires(set(),{root.id})
        self.drag['wire_snapshot']={key:copy.deepcopy(self.wires[key].__dict__) for key in ids}

    def begin_segment_drag(self,item,index,point,modifiers):
        multi=item.isSelected() and len(self.scene.selectedItems())>1
        self.begin_drag(item,point,modifiers)
        if not self.drag:return
        if self.drag['kind'] in ('end','junction') or multi:return
        if modifiers&Qt.KeyboardModifier.AltModifier and item.key in self.floating:return
        self.doc.freeze_wire(item.w)
        self.drag.update(kind='segment',index=nearest_segment(route(self.doc,item.w),point.x(),point.y()),original=copy.deepcopy(item.w.vertices),host=None)
        item.active_segment=self.drag['index']
        self.capture_wire_component(item)
        for segment in item.segments:segment.update()

    def capture_selected_labels(self):
        d=self.drag
        if d and d['kind']=='objects':
            d['label_anchors']={i.key:QPointF(i.pos()) for i in self.scene.selectedItems() if i.kind=='label' and i.label.wire_id not in self.affected_wires(d['members'],d['wires'])}

    def move_drag(self,point):
        d=self.drag
        if not d:return
        if d['kind']=='resize':
            item=d['item']
            if item.kind=='node':resize_node(item.n,d['original'],d['corner'],point.x(),point.y());item.refresh_layout();self.refresh_geometry(members={item.key})
            else:
                c=item.c;limit=COORD_LIMIT if c.kind=='group' else 2000
                c.w=min(limit,max(100,snap(point.x()-c.x)));c.h=min(limit,max(40,snap(point.y()-c.y)));item.refresh_layout()
            return
        if d['kind']=='junction':
            item=d['item'];self.doc.move_junction(item.w,point.x(),point.y());self.refresh_geometry(wires={item.key,item.w.join_wire});return
        if d['kind']=='label':
            delta=point-d['point'];anchor=d['anchor']+delta;near=self.nearest_wire(anchor)
            item=d['item']
            if near:item.label.wire_id=near[0]
            wire=self.wire_items[item.label.wire_id]
            item.label.position=project_to_path(wire.points,anchor.x(),anchor.y())[0];item.refresh();return
        for key,state in d.get('wire_snapshot',{}).items():
            self.wires[key].__dict__.clear();self.wires[key].__dict__.update(copy.deepcopy(state))
        super().move_drag(point)
        if self.drag and d.get('wire_snapshot'):
            self.refresh_geometry(wires=set(d['wire_snapshot']))
            item=d['item'];item.active_segment=nearest_segment(item.points,point.x(),point.y())
            for segment in item.segments:segment.update()
        if self.drag and d['kind']=='objects':
            for key,anchor in d.get('label_anchors',{}).items():
                item=self.label_items[key];offset=point-d['point'];p=anchor+offset
                item.label.position=project_to_path(self.wire_items[item.label.wire_id].points,p.x(),p.y())[0];item.refresh()

    def finish_drag(self):
        d=self.drag;extend=None
        if d and d['kind']=='end' and self.doc.serialize()==d['before']:
            w=d['item'].w;ep=w.source or w.target
            if ep and not w.join_wire:
                points=route(self.doc,w)
                if w.target:points=list(reversed(points))
                extend=(ep,w.id,[list(p) for p in points[1:]])
        super().finish_drag()
        if extend:self.start_wire(*extend)

    def undo(self):
        self.cancel_drawing();destination=(self.doc.export_path,self.doc.top,self.doc.language);super().undo()
        if destination[0]:self.doc.export_path,self.doc.top,self.doc.language=destination
        self.update_title()

    def redo(self):
        self.cancel_drawing();destination=(self.doc.export_path,self.doc.top,self.doc.language);super().redo()
        if destination[0]:self.doc.export_path,self.doc.top,self.doc.language=destination
        self.update_title()

    def may_discard(self):
        self.cancel_drawing();self.cancel_drag()
        if self.doc.serialize()==self.saved:return True
        answer=QMessageBox.question(self,'Unsaved Schematic','Save changes to the current schematic?',QMessageBox.StandardButton.Save|QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Save)
        return self.save() if answer==QMessageBox.StandardButton.Save else answer==QMessageBox.StandardButton.Discard

    def new_document(self):
        if not self.may_discard():return
        self.doc=Document();self.path=None;self.saved=self.doc.serialize();self.history=[];self.future=[];self.rebuild();self.view.centerOn(400,300);self.update_title()

    def load(self,path):self.cancel_drawing();return super().load(path)

    def save(self,save_as=False,path=None):
        self.cancel_drag()
        if path is None:
            path=str(self.path) if self.path and not save_as else ''
            if not path:path,_=QFileDialog.getSaveFileName(self,'Save Schematic As',str(self.path or 'schematic.vsch'),'VerilogCanvas (*.vsch)')
        if not path:return False
        if not str(path).lower().endswith('.vsch'):path=str(path)+'.vsch'
        try:self.doc.save(path)
        except (ValueError,OSError) as exc:self.error('Could Not Save Schematic',exc);return False
        self.path=Path(path);self.saved=self.doc.serialize();self.update_title();self.statusBar().showMessage(f'Saved: {path}',5000);return True

    def export_document(self,path):
        doc=copy.deepcopy(self.doc)
        if path:
            target=Path(path)
            if target.suffix.lower() not in ('.v','.sv'):raise DesignError('Choose a .v or .sv output file')
            doc.top=identifier(target.stem);doc.language='systemverilog' if target.suffix.lower()=='.sv' else 'verilog';doc.export_path=str(target.resolve())
        return doc,doc.verilog()

    def export(self,save_as=False,path=None):
        ext='.sv' if self.doc.language=='systemverilog' else '.v'
        if path is None:
            path=self.doc.export_path if not save_as else ''
            if path and Path(path).suffix.lower()!=ext:path=''
            if not path:
                suggested=Path(self.doc.export_path).with_suffix(ext) if self.doc.export_path else (self.path.parent if self.path else Path('.'))/(self.doc.top+ext)
                filters='SystemVerilog (*.sv);;Verilog (*.v)' if ext=='.sv' else 'Verilog (*.v);;SystemVerilog (*.sv)'
                path,chosen=QFileDialog.getSaveFileName(self,'Export HDL As',str(suggested),filters)
                if path and not Path(path).suffix:path+='.sv' if '*.sv' in chosen else '.v'
        if not path:return False
        temporary=None
        try:
            doc,source=self.export_document(path);target=Path(doc.export_path)
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',newline='\n',dir=target.parent,prefix='.'+target.name+'.',suffix='.tmp',delete=False) as stream:
                temporary=Path(stream.name);stream.write(source)
            temporary.replace(target);temporary=None
        except (ValueError,OSError) as exc:self.error('Could Not Export HDL',exc);return False
        finally:
            if temporary:temporary.unlink(missing_ok=True)
        self.doc.top=doc.top;self.doc.language=doc.language;self.doc.export_path=doc.export_path;self.update_title()
        self.statusBar().showMessage(f'Exported: {target}',5000)
        notice=QLabel('Exported: '+target.name,self.view);notice.setStyleSheet('background: #23354a; color: #e4eefb; padding: 12px; border: 1px solid #65ed8a;');notice.adjustSize()
        notice.move(max(10,self.view.width()-notice.width()-30),max(10,self.view.height()-notice.height()-30));notice.show();QTimer.singleShot(2200,notice.deleteLater)
        return True

    def preview_hdl(self):
        try:
            ext='.sv' if self.doc.language=='systemverilog' else '.v'
            path=self.doc.export_path if self.doc.export_path and Path(self.doc.export_path).suffix.lower()==ext else ''
            _,source=self.export_document(path)
        except ValueError as exc:self.error('Could Not Generate HDL',exc);return
        PreviewDialog(self,source).exec()

    def render_png(self,path):
        self.cancel_drawing();self.cancel_drag();selected=self.scene.selectedItems();self.scene.clearSelection();self.exporting=True
        try:
            bounds=self.scene.itemsBoundingRect().adjusted(-40,-40,40,40)
            if bounds.width()<=0 or bounds.height()<=0:raise DesignError('The schematic is empty')
            scale=min(2.,16384/max(bounds.width(),bounds.height()),math.sqrt(32_000_000/(bounds.width()*bounds.height())))
            width=max(1,math.ceil(bounds.width()*scale));height=max(1,math.ceil(bounds.height()*scale))
            image=QImage(width,height,QImage.Format.Format_ARGB32_Premultiplied)
            if image.isNull():raise DesignError('Not enough memory to render this schematic')
            image.fill(QColor(BG));p=QPainter(image)
            try:
                p.setRenderHints(QPainter.RenderHint.Antialiasing|QPainter.RenderHint.TextAntialiasing)
                p.save();p.scale(scale,scale);p.translate(-bounds.x(),-bounds.y());self.view.drawBackground(p,bounds);p.restore()
                self.scene.render(p,QRectF(0,0,width,height),bounds,Qt.AspectRatioMode.IgnoreAspectRatio)
            finally:p.end()
            if not image.save(str(path),'PNG'):raise OSError('Could not write PNG file')
            return width,height
        finally:
            self.exporting=False
            for item in selected:item.setSelected(True)

    def export_png(self):
        path,_=QFileDialog.getSaveFileName(self,'Export Schematic as PNG',str(self.path.with_suffix('.png') if self.path else Path(self.doc.top+'.png')),'PNG image (*.png)')
        if not path:return
        if not path.lower().endswith('.png'):path+='.png'
        try:
            w,h=self.render_png(path);self.statusBar().showMessage(f'Exported PNG: {w} × {h} — {path}',6000)
        except (OSError,ValueError) as exc:self.error('Could Not Export PNG',exc)

    def about(self):
        QMessageBox.information(self,'VerilogCanvas Qt 1.2.2',
            'Verilog / SystemVerilog schematic editor\n\n'
            'Click a port, then another port or wire to connect. Click intermediate bends; Enter or double-click finishes a dangling wire. Click an open circle to extend; drag it to move.\n\n'
            'Drag wire segments perpendicular to their direction. Drag junctions along their host wire. Alt+drag moves a detached wire component as a whole. Double-click wires to name nets. Matching labels connect separate wires.\n\n'
            'Double-click objects to edit. Drag module corners to resize; select comments to expose their resize handle. Drag empty space for area selection. Groups include modules, I/O and ordinary comments; Ctrl+drag moves a member independently. Ctrl+click then Copy copies only that member.\n\n'
            'Ctrl+wheel: zoom; wheel / Shift+wheel: scroll; middle drag: pan; Home: fit. Dots / Lines / Off changes only the displayed grid.\n\n'
            'Ctrl+S: save schematic; Ctrl+Shift+S: save as. Ctrl+E: export to the remembered output file; Ctrl+Shift+E: export as; Ctrl+P: preview. Esc cancels drawing or dragging.\n\n'
            'Connection errors are shown in red; hover for details. They can be repaired without changing the layout.\n'
            'Inline HDL is stored as plain text and inserted into the shared top-level scope. Compile generated HDL with your synthesis tools.')


def main():
    app=QApplication(sys.argv);app.setStyle('Fusion');window=EditorWindow();window.show()
    if len(sys.argv)>1:QTimer.singleShot(0,lambda:window.load(sys.argv[1]))
    sys.exit(app.exec())

if __name__=='__main__':main()
